#!/usr/bin/env python3
"""
Sistema DUAL RADAR - GRAVATÁ
Baseado 100% no codigo_sj1.py com sistema robusto de tracking
Duas áreas (interna + externa) → MESMA PLANILHA
"""

import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
import logging
import os
import traceback
import time
import json
import serial
import threading
import serial.tools.list_ports
from dotenv import load_dotenv

# Configuração básica de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('gravata_dual_radar.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('gravata_dual_radar')

# Configurando o nível de log para outros módulos
logging.getLogger('urllib3').setLevel(logging.WARNING)
logging.getLogger('gspread').setLevel(logging.WARNING)

load_dotenv()

# ✅ CONFIGURAÇÃO DOS DOIS RADARES PARA GRAVATÁ (BASEADO NO codigo_sj1.py)
RADAR_CONFIGS = [
    {
        'id': 'RADAR_GRAVATA_EXTERNO',
        'name': 'Contador Gravatá Externo',
        'port': '/dev/ttyACM0',
        'baudrate': 115200,
        'spreadsheet_id': '1ACu8Qmicxv7Av-1nAK_dIDbcD_RJBizk2iXspixK2Gg',
        'color': '🔴',
        'area_tipo': 'EXTERNA',
        'description': 'Gravatá Externa: multi-pessoa simultânea, 8.3Hz, até 8 pessoas'
    },
    {
        'id': 'RADAR_GRAVATA_INTERNO',
        'name': 'Contador Gravatá Interno',
        'port': '/dev/ttyACM1', 
        'baudrate': 115200,
        'spreadsheet_id': '1ACu8Qmicxv7Av-1nAK_dIDbcD_RJBizk2iXspixK2Gg',
        'color': '🔵',
        'area_tipo': 'INTERNA',
        'description': 'Gravatá Interna: multi-pessoa simultânea, 8.3Hz, até 8 pessoas'
    }
]

# Configurações gerais
CREDENTIALS_FILE = 'serial_radar/credenciais.json'

class GoogleSheetsManager:
    def __init__(self, creds_path, spreadsheet_id, radar_id):
        SCOPES = [
            'https://www.googleapis.com/auth/spreadsheets',
            'https://www.googleapis.com/auth/drive',
            'https://www.googleapis.com/auth/drive.file'
        ]
        self.radar_id = radar_id
        self.spreadsheet_id = spreadsheet_id
        self.creds = Credentials.from_service_account_file(creds_path, scopes=SCOPES)
        self.gc = gspread.authorize(self.creds)
        
        try:
            self.spreadsheet = self.gc.open_by_key(spreadsheet_id)
            logger.info(f"✅ Planilha Gravatá conectada: {self.spreadsheet.title}")
        except Exception as e:
            logger.error(f"❌ Erro ao conectar à planilha: {e}")
            raise
            
        try:
            self.worksheet = self.spreadsheet.get_worksheet(0)
            logger.info(f"✅ Worksheet selecionada: {self.worksheet.title}")
        except Exception as e:
            logger.error(f"❌ Erro ao selecionar worksheet: {e}")
            raise
        
        self._setup_headers()

    def _setup_headers(self):
        """Configura cabeçalhos específicos para Gravatá Dual (diferente do Santa Cruz)"""
        try:
            headers = self.worksheet.row_values(1)
            # Campos específicos para GRAVATÁ DUAL - mostra dados de cada área
            expected_headers = [
                'radar_id',           # ID do radar (EXTERNO/INTERNO)
                'timestamp',          # Data/hora
                'area_tipo',          # EXTERNA ou INTERNA
                'person_count',       # Pessoas simultâneas nesta área
                'person_id',          # ID da pessoa/grupo
                'zone',               # Zona específica da área
                'distance',           # Distância (metros)
                'confidence',         # Confiança da detecção (%)
                'total_detected',     # Total acumulativo desta área
                'max_simultaneous',   # Máximo simultâneo desta área
                'area_status'         # Status da área (ATIVA/VAZIA)
            ]
            
            if not headers or len(headers) < 11:
                logger.info("🔧 Configurando cabeçalhos Gravatá Dual (11 campos específicos)")
                self.worksheet.clear()
                self.worksheet.append_row(expected_headers)
            else:
                logger.info("✅ Cabeçalhos Gravatá Dual verificados")
                    
        except Exception as e:
            logger.warning(f"⚠️ Erro ao configurar cabeçalhos: {e}")

class ZoneManager:
    def __init__(self, area_tipo):
        self.area_tipo = area_tipo
        
        # Configuração baseada no tipo de área
        if area_tipo == 'EXTERNA':
            # Área externa: apenas 2 zonas simples baseadas na distância
            self.ZONA_CONFIGS = {
                'AREA_INTERESSE': {
                    'x_min': -4.0, 'x_max': 4.0,
                    'y_min': 0.0, 'y_max': 8.0,
                    'distance_range': (0.3, 4.0)  # Perto = área de interesse (aumentado para 4.0m)
                },
                'AREA_PASSAGEM': {
                    'x_min': -4.0, 'x_max': 4.0,
                    'y_min': 0.0, 'y_max': 8.0,
                    'distance_range': (4.0, 8.0)  # Afastado = área de passagem
                }
            }
        else:  # INTERNA
            # Área interna: ativações específicas iguais ao Santa Cruz
            self.ZONA_CONFIGS = {
                'SALA_REBOCO': {
                    'x_min': -3.5, 'x_max': -0.3,
                    'y_min': 0.3, 'y_max': 3.8,
                    'distance_range': (1.0, 4.0)
                },
                'IGREJINHA': {
                    'x_min': -3.0, 'x_max': -0.2,
                    'y_min': 2.8, 'y_max': 6.0,
                    'distance_range': (2.5, 6.0)
                },
                'CENTRO': {
                    'x_min': -1.0, 'x_max': 1.0,
                    'y_min': 1.0, 'y_max': 4.5,
                    'distance_range': (2.0, 5.0)
                },
                'ARGOLA': {
                    'x_min': 0.3, 'x_max': 3.0,
                    'y_min': 4.0, 'y_max': 7.5,
                    'distance_range': (4.0, 8.0)
                },
                'BEIJO': {
                    'x_min': 0.5, 'x_max': 3.5,
                    'y_min': 2.0, 'y_max': 5.5,
                    'distance_range': (3.5, 7.5)
                },
                'PESCARIA': {
                    'x_min': 0.8, 'x_max': 4.0,
                    'y_min': 0.2, 'y_max': 4.0,
                    'distance_range': (4.0, 9.0)
                }
            }
        
    def get_zone(self, x, y):
        """Determinar zona baseada na posição e tipo de área"""
        distance = self.get_distance(x, y)
        
        # Verifica cada zona baseada na posição X,Y e distância
        for zona_name, config in self.ZONA_CONFIGS.items():
            if (config['x_min'] <= x <= config['x_max'] and
                config['y_min'] <= y <= config['y_max'] and
                config['distance_range'][0] <= distance <= config['distance_range'][1]):
                return zona_name
        
        # Zonas de fallback baseadas na distância e área
        if self.area_tipo == 'EXTERNA':
            # Área externa: apenas interesse vs passagem
            if distance <= 3.5:
                return 'AREA_INTERESSE'
            else:
                return 'AREA_PASSAGEM'
        else:  # INTERNA
            # Área interna: igual ao Santa Cruz - se não está em ativação específica
            return 'FORA_ATIVACOES'
    
    def get_distance(self, x, y):
        """Calcular distância do radar"""
        import math
        return math.sqrt(x**2 + y**2)
    
    def get_zone_description(self, zone_name):
        """Retorna descrição amigável da zona"""
        descriptions = {
            # Área externa (2 zonas simples)
            'AREA_INTERESSE': 'Área de Interesse',
            'AREA_PASSAGEM': 'Área de Passagem',
            # Área interna (ativações específicas iguais ao Santa Cruz)
            'SALA_REBOCO': 'Sala de Reboco',
            'IGREJINHA': 'Igrejinha', 
            'CENTRO': 'Centro',
            'ARGOLA': 'Jogo da Argola',
            'BEIJO': 'Barraca do Beijo',
            'PESCARIA': 'Pescaria',
            'FORA_ATIVACOES': 'Fora das Ativações'
        }
        return descriptions.get(zone_name, zone_name)

class SingleRadarCounter:
    def __init__(self, config):
        self.config = config
        self.radar_id = config['id']
        self.radar_name = config['name']
        self.area_tipo = config['area_tipo']
        self.port = config['port']
        self.baudrate = config['baudrate']
        self.color = config['color']
        self.description = config['description']
        
        self.serial_connection = None
        self.is_running = False
        self.receive_thread = None
        self.gsheets_manager = None
        self.zone_manager = ZoneManager(self.area_tipo)
        
        # Sistema robusto de contagem de pessoas (igual ao codigo_sj1)
        self.current_people = {}
        self.previous_people = {}
        self.people_history = {}
        self.total_people_detected = 0
        self.max_simultaneous_people = 0
        self.session_start_time = datetime.now()
        
        # Configurações de tracking
        self.exit_timeout = 3.0
        self.reentry_timeout = 10.0
        self.last_update_time = time.time()
        
        # Controle de escrita no Google Sheets (MAIS CONSERVADOR)
        self.last_sheets_write = 0
        self.sheets_write_interval = 60.0  # Aumentado para 60 segundos
        self.pending_data = []
        self.max_pending_lines = 5   # Reduzido para 5 linhas para evitar spam
        self.min_interval_between_adds = 10.0  # Mínimo 10s entre adições ao buffer
        
        # Estatísticas detalhadas
        self.entries_count = 0
        self.exits_count = 0
        self.unique_people_today = set()
        self.last_data_add_time = 0  # Controle temporal para evitar spam

    def find_serial_port(self):
        """Detecta automaticamente a porta serial"""
        ports = list(serial.tools.list_ports.comports())
        if not ports:
            logger.error("Nenhuma porta serial encontrada!")
            return None
        
        logger.info(f"🔍 Portas seriais disponíveis:")
        for port in ports:
            logger.info(f"   📡 {port.device} - {port.description}")
        
        # Primeiro tenta a porta configurada
        for port in ports:
            if port.device == self.port:
                logger.info(f"✅ Porta configurada encontrada: {self.port}")
                return self.port
        
        # Se não encontrou, procura por dispositivos apropriados
        for port in ports:
            desc_lower = port.description.lower()
            if any(term in desc_lower for term in
                  ['usb', 'serial', 'uart', 'cp210', 'ch340', 'ft232', 'arduino', 'esp32', 'jtag', 'modem']):
                logger.warning(f"Porta {self.port} não encontrada, tentando usar {port.device}")
                return port.device
        
        logger.error("Nenhuma porta adequada encontrada!")
        return None

    def connect(self):
        """Conecta à porta serial com reconexão automática"""
        max_attempts = 3
        
        for attempt in range(max_attempts):
            try:
                # Verifica se a porta ainda existe
                if not os.path.exists(self.port):
                    logger.warning(f"{self.color} Porta {self.port} não existe mais, detectando nova porta...")
                    detected_port = self.find_serial_port()
                    if detected_port:
                        self.port = detected_port
                    else:
                        logger.error(f"{self.color} Tentativa {attempt + 1}/{max_attempts}: Nenhuma porta encontrada")
                        time.sleep(2)
                        continue
                
                # Fecha conexão anterior se existir
                if hasattr(self, 'serial_connection') and self.serial_connection:
                    try:
                        self.serial_connection.close()
                    except:
                        pass
                
                logger.info(f"{self.color} Tentativa {attempt + 1}/{max_attempts}: Conectando à porta {self.port}...")
                
                self.serial_connection = serial.Serial(
                    port=self.port,
                    baudrate=self.baudrate,
                    timeout=2,
                    write_timeout=2,
                    bytesize=serial.EIGHTBITS,
                    parity=serial.PARITY_NONE,
                    stopbits=serial.STOPBITS_ONE
                )
                
                # Aguarda estabilização
                time.sleep(3)
                
                # Testa a conexão
                if self.serial_connection.is_open:
                    logger.info(f"{self.color} ✅ Conexão estabelecida com sucesso!")
                    return True
                else:
                    logger.warning(f"{self.color} ⚠️ Porta aberta mas não está responsiva")
                    
            except serial.SerialException as e:
                logger.error(f"{self.color} ❌ Erro serial na tentativa {attempt + 1}: {str(e)}")
            except Exception as e:
                logger.error(f"{self.color} ❌ Erro geral na tentativa {attempt + 1}: {str(e)}")
            
            if attempt < max_attempts - 1:
                wait_time = (attempt + 1) * 2
                logger.info(f"{self.color} ⏳ Aguardando {wait_time}s antes da próxima tentativa...")
                time.sleep(wait_time)
        
        logger.error(f"{self.color} ❌ Falha ao conectar após {max_attempts} tentativas")
        return False

    def start(self, gsheets_manager):
        """Inicia o radar"""
        self.gsheets_manager = gsheets_manager
        
        if not self.connect():
            return False
        
        self.is_running = True
        self.receive_thread = threading.Thread(target=self.receive_data_loop, daemon=True)
        self.receive_thread.start()
        
        logger.info(f"{self.color} 🚀 Radar {self.area_tipo} iniciado com sucesso!")
        return True

    def stop(self):
        """Para o radar"""
        self.is_running = False
        
        if self.serial_connection:
            try:
                self.serial_connection.close()
            except:
                pass
        
        if self.receive_thread and self.receive_thread.is_alive():
            self.receive_thread.join(timeout=2)
        
        logger.info(f"{self.color} 🛑 Radar {self.area_tipo} parado!")

    def receive_data_loop(self):
        """Loop principal de recebimento de dados com reconexão robusta"""
        import sys
        import os
        buffer = ""
        consecutive_errors = 0
        max_consecutive_errors = 5
        
        logger.info(f"{self.color} 🔄 Loop de dados {self.area_tipo} iniciado...")
        
        while self.is_running:
            try:
                # Verifica se a conexão está ativa
                if not self.serial_connection or not self.serial_connection.is_open:
                    logger.warning(f"{self.color} ⚠️ Conexão perdida, tentando reconectar...")
                    if self.connect():
                        consecutive_errors = 0
                        buffer = ""
                        continue
                    else:
                        consecutive_errors += 1
                        time.sleep(5)
                        continue
                
                # Tenta ler dados
                in_waiting = self.serial_connection.in_waiting or 0
                data = self.serial_connection.read(in_waiting or 1)
                
                if data:
                    consecutive_errors = 0
                    text = data.decode('utf-8', errors='ignore')
                    buffer += text
                    
                    if '\n' in buffer:
                        lines = buffer.split('\n')
                        buffer = lines[-1]
                        
                        for line in lines[:-1]:
                            line = line.strip()
                            if not line or not line.startswith('{'):
                                continue
                            
                            try:
                                data_json = json.loads(line)
                                self.process_json_data(data_json)
                            except json.JSONDecodeError as e:
                                logger.debug(f"Linha JSON inválida ignorada: {line[:50]}...")
                            except Exception as e:
                                logger.error(f"Erro ao processar linha JSON: {e}")
                
                time.sleep(0.01)
                
            except serial.SerialException as e:
                consecutive_errors += 1
                error_msg = str(e)
                
                if "Device not configured" in error_msg or "Errno 6" in error_msg:
                    logger.error(f"{self.color} ❌ Dispositivo desconectado (Erro {consecutive_errors}/{max_consecutive_errors})")
                    try:
                        if self.serial_connection:
                            self.serial_connection.close()
                    except:
                        pass
                    self.serial_connection = None
                    time.sleep(2)
                elif "Errno 5" in error_msg or "Input/output error" in error_msg:
                    logger.error(f"{self.color} ❌ Erro de I/O - dispositivo pode ter sido removido")
                    self.serial_connection = None
                    time.sleep(3)
                else:
                    logger.error(f"{self.color} ❌ Erro serial: {error_msg}")
                    time.sleep(1)
                
                if consecutive_errors >= max_consecutive_errors:
                    logger.warning(f"{self.color} ⚠️ Muitos erros consecutivos, pausando por 10s...")
                    time.sleep(10)
                    consecutive_errors = 0
                    
            except Exception as e:
                consecutive_errors += 1
                logger.error(f"{self.color} ❌ Erro inesperado no loop: {str(e)}")
                time.sleep(2)
                
                if consecutive_errors >= max_consecutive_errors:
                    logger.warning(f"{self.color} ⚠️ Muitos erros consecutivos, pausando...")
                    time.sleep(10)
                    consecutive_errors = 0

    def convert_timestamp(self, timestamp_ms):
        """Converte timestamp de milissegundos para formato brasileiro"""
        try:
            dt = datetime.now()
            return dt.strftime('%d/%m/%Y %H:%M:%S')
        except Exception as e:
            logger.debug(f"Erro na conversão de timestamp: {e}")
            return datetime.now().strftime('%d/%m/%Y %H:%M:%S')

    def format_duration(self, duration_ms):
        """Formata duração em milissegundos para formato legível"""
        try:
            if duration_ms < 1000:
                return f"{int(duration_ms)}ms"
            elif duration_ms < 60000:
                seconds = duration_ms / 1000
                return f"{seconds:.1f}s"
            elif duration_ms < 3600000:
                minutes = duration_ms / 60000
                return f"{minutes:.1f}min"
            else:
                hours = duration_ms / 3600000
                return f"{hours:.1f}h"
        except:
            return "N/A"

    def update_people_count(self, person_count, active_people):
        """Sistema CORRIGIDO de tracking para eventos - lógica precisa de entrada/saída"""
        current_time = time.time()
        
        current_people_dict = {}
        
        for i, person in enumerate(active_people):
            x_pos = person.get('x_pos', 0)
            y_pos = person.get('y_pos', 0) 
            distance = person.get('distance_smoothed', person.get('distance_raw', 0))
            
            # ✅ CALCULA ZONA ESPECÍFICA DA ÁREA usando coordenadas x,y
            zone = self.zone_manager.get_zone(x_pos, y_pos)
            person["zone"] = zone  # Atualiza o objeto pessoa com a zona correta
            
            # ID baseado na posição arredondada (estável para pessoa parada)
            stable_id = f"P_{self.area_tipo}_{zone}_{distance:.1f}_{i}"
            
            # Procura se já existe pessoa similar (mesma zona, distância similar)
            found_existing = None
            for existing_id, existing_person in self.current_people.items():
                existing_dist = existing_person.get('distance_smoothed', 0)
                existing_zone = existing_person.get('zone', '')
                
                if (existing_zone == zone and 
                    abs(existing_dist - distance) < 0.3):
                    found_existing = existing_id
                    break
            
            if found_existing:
                current_people_dict[found_existing] = person
                current_people_dict[found_existing]['last_seen'] = current_time
            else:
                person['first_seen'] = current_time
                person['last_seen'] = current_time
                current_people_dict[stable_id] = person
        
        # Detecta ENTRADAS REAIS
        new_entries = []
        for person_id, person_info in current_people_dict.items():
            if person_id not in self.current_people:
                is_really_new = True
                for old_id, old_person in self.previous_people.items():
                    old_zone = old_person.get('zone', '')
                    old_dist = old_person.get('distance_smoothed', 0)
                    new_zone = person_info.get('zone', '')
                    new_dist = person_info.get('distance_smoothed', 0)
                    
                    if (old_zone == new_zone and 
                        abs(old_dist - new_dist) < 0.5 and
                        (current_time - old_person.get('last_seen', 0)) < 2.0):
                        is_really_new = False
                        break
                
                if is_really_new:
                    new_entries.append(person_id)
                    self.total_people_detected += 1
                    self.entries_count += 1
                    self.unique_people_today.add(person_id)
                    zone = person_info.get('zone', 'DESCONHECIDA')
                    dist = person_info.get('distance_smoothed', 0)
                    logger.info(f"🆕 ENTRADA {self.area_tipo}: {zone} {dist:.1f}m (Total: {self.total_people_detected})")
        
        # Detecta SAÍDAS REAIS
        exits = []
        for person_id, person_info in self.current_people.items():
            if person_id not in current_people_dict:
                last_seen = person_info.get('last_seen', 0)
                if (current_time - last_seen) > 1.0:
                    exits.append(person_id)
                    self.exits_count += 1
                    zone = person_info.get('zone', 'DESCONHECIDA')
                    dist = person_info.get('distance_smoothed', 0)
                    logger.info(f"🚪 SAÍDA {self.area_tipo}: {zone} {dist:.1f}m")
        
        # Atualiza estado
        self.previous_people = self.current_people.copy()
        self.current_people = current_people_dict
        
        # Atualiza máximo simultâneo
        current_simultaneous = len(current_people_dict)
        if current_simultaneous > self.max_simultaneous_people:
            self.max_simultaneous_people = current_simultaneous
            logger.info(f"📊 NOVO MÁXIMO {self.area_tipo}: {self.max_simultaneous_people} pessoas")
        
        self.last_update_time = current_time

    def process_json_data(self, data_json):
        """Processa dados JSON multi-pessoa v4.2 recebidos do radar"""
        try:
            # DEBUG: Mostra dados brutos recebidos
            logger.debug(f"JSON recebido ({self.area_tipo}): {data_json}")

            radar_id = data_json.get("radar_id", self.radar_id)
            timestamp_ms = data_json.get("timestamp_ms", 0)
            person_count = data_json.get("person_count", 0)
            active_people = data_json.get("active_people", [])

            formatted_timestamp = self.convert_timestamp(timestamp_ms)

            # Atualiza contadores locais
            self.update_people_count(person_count, active_people)

            # Limpa o terminal antes do display (igual Santa Cruz)
            os.system('clear')

            # Display em tempo real
            print(f"\n{self.color} ═══ GRAVATÁ {self.area_tipo} - TRACKING AVANÇADO ═══")
            print(f"⏰ {formatted_timestamp}")
            print(f"📡 {radar_id} | 👥 ATIVAS: {person_count}")
            print(f"🎯 TOTAL {self.area_tipo}: {self.total_people_detected} | 📊 MÁXIMO: {self.max_simultaneous_people}")
            print(f"🔄 ENTRADAS: {self.entries_count} | 🚪 SAÍDAS: {self.exits_count}")

            if active_people and len(active_people) > 0:
                print(f"\n👥 PESSOAS NA ÁREA {self.area_tipo} ({len(active_people)}):")
                print(f"{'Zona':<20} {'Dist(m)':<7} {'X,Y':<10} {'Conf%':<5} {'Status':<8}")
                print("-" * 55)

                current_time = time.time()
                for i, person in enumerate(active_people):
                    confidence = person.get("confidence", 0)
                    # Corrigir: usar distance_smoothed OU distance_raw
                    distance_smoothed = person.get("distance_smoothed", person.get("distance_raw", 0))
                    x_pos = person.get("x_pos", 0)
                    y_pos = person.get("y_pos", 0)
                    stationary = person.get("stationary", False)

                    # ✅ CALCULA ZONA ESPECÍFICA DA ÁREA usando coordenadas x,y
                    zone = self.zone_manager.get_zone(x_pos, y_pos)
                    person["zone"] = zone  # Atualiza o objeto pessoa com a zona correta

                    status = "Parado" if stationary else "Móvel"
                    pos_str = f"{x_pos:.1f},{y_pos:.1f}"

                    zone_desc = self.zone_manager.get_zone_description(zone)[:19]
                    print(f"{zone_desc:<20} {distance_smoothed:<7.2f} {pos_str:<10} {confidence:<5}% {status:<8}")

                # Envia dados para planilha (formato específico Gravatá) - COM CONTROLE TEMPORAL
                if self.gsheets_manager:
                    current_time = time.time()

                    # EVITA SPAM: Só adiciona se passou tempo suficiente desde última adição
                    if (current_time - self.last_data_add_time) >= self.min_interval_between_adds:
                        avg_confidence = sum(p.get("confidence", 0) for p in active_people) / len(active_people)
                        zones_detected = list(set(p.get("zone", "N/A") for p in active_people))
                        zones_str = ",".join(sorted(zones_detected))

                        if len(active_people) == 1:
                            person_description = f"Pessoa_{self.area_tipo}"
                        elif len(active_people) <= 3:
                            person_description = f"Grupo_Pequeno_{self.area_tipo}"
                        elif len(active_people) <= 10:
                            person_description = f"Grupo_Medio_{self.area_tipo}"
                        else:
                            person_description = f"Grupo_Grande_{self.area_tipo}"

                        # Corrigir: usar distance_smoothed OU distance_raw
                        avg_distance = sum(p.get('distance_smoothed', p.get('distance_raw', 0)) for p in active_people) / len(active_people)

                        row = [
                            radar_id,                                    # 1. radar_id
                            formatted_timestamp,                         # 2. timestamp  
                            self.area_tipo,                             # 3. area_tipo (EXTERNA/INTERNA)
                            len(active_people),                         # 4. person_count
                            person_description,                         # 5. person_id
                            zones_str,                                  # 6. zone
                            f"{avg_distance:.1f}",                      # 7. distance
                            f"{avg_confidence:.0f}",                    # 8. confidence
                            self.total_people_detected,                 # 9. total_detected
                            self.max_simultaneous_people,               # 10. max_simultaneous
                            'ATIVA'                                     # 11. area_status
                        ]
                        self.pending_data.append(row)
                        self.last_data_add_time = current_time
                        logger.info(f"📊 Dados {self.area_tipo} adicionados ao buffer ({len(self.pending_data)}/5)")
                    else:
                        time_remaining = self.min_interval_between_adds - (current_time - self.last_data_add_time)
                        logger.debug(f"⏳ {self.area_tipo}: Aguardando {time_remaining:.1f}s para próxima adição")

                print(f"\n💡 ÁREA {self.area_tipo}: {len(active_people)} pessoa(s) ATIVAS")

            else:
                print(f"\n👻 Área {self.area_tipo} vazia no momento.")

                # Dados zerados para área vazia - COM CONTROLE TEMPORAL
                if self.gsheets_manager and len(self.previous_people) > 0:
                    current_time = time.time()

                    # EVITA SPAM de status vazio: Só adiciona se passou tempo suficiente
                    if (current_time - self.last_data_add_time) >= self.min_interval_between_adds:
                        row = [
                            radar_id,                           # 1. radar_id
                            formatted_timestamp,                # 2. timestamp
                            self.area_tipo,                    # 3. area_tipo
                            0,                                 # 4. person_count
                            f"Vazia_{self.area_tipo}",         # 5. person_id
                            "VAZIA",                           # 6. zone
                            "0",                               # 7. distance
                            "0",                               # 8. confidence
                            self.total_people_detected,        # 9. total_detected
                            self.max_simultaneous_people,      # 10. max_simultaneous
                            'VAZIA'                            # 11. area_status
                        ]
                        self.pending_data.append(row)
                        self.last_data_add_time = current_time
                        logger.info(f"📊 Status VAZIA {self.area_tipo} adicionado ao buffer")

            print("=" * 60)

            # Envia dados controladamente
            self.send_pending_data_to_sheets()

        except Exception as e:
            logger.error(f"Erro ao processar dados JSON {self.area_tipo}: {e}")

    def send_pending_data_to_sheets(self):
        """Envia dados para Google Sheets de forma controlada (IGUAL AO SANTA CRUZ)"""
        try:
            current_time = time.time()
            
            # Verifica se já passou tempo suficiente desde último envio OU se tem 5+ linhas
            time_to_send = (current_time - self.last_sheets_write) >= self.sheets_write_interval
            buffer_full = len(self.pending_data) >= self.max_pending_lines
            
            if not time_to_send and not buffer_full:
                return  # Ainda não é hora de enviar
            
            # Se não há dados pendentes, não faz nada
            if not self.pending_data or not self.gsheets_manager:
                return
            
            # Pega apenas os dados mais recentes (máximo 5 linhas por vez)
            data_to_send = self.pending_data[-self.max_pending_lines:] if len(self.pending_data) > self.max_pending_lines else self.pending_data
            
            # Envia em lote (mais eficiente)
            if data_to_send:
                logger.info(f"📊 Enviando {len(data_to_send)} linhas {self.area_tipo} para planilha...")
                
                # Envia todas as linhas de uma vez (batch) - COM PAUSA MAIOR
                for row in data_to_send:
                    self.gsheets_manager.worksheet.append_row(row)
                    time.sleep(2.0)  # Pausa de 2 segundos entre linhas para evitar sobrecarga
                
                logger.info(f"✅ {len(data_to_send)} linhas {self.area_tipo} enviadas!")
                
                # Atualiza controles
                self.last_sheets_write = current_time
                self.pending_data = []  # Limpa dados enviados
                
        except Exception as e:
            logger.error(f"❌ Erro ao enviar dados {self.area_tipo}: {e}")
            # Em caso de erro, mantém dados para próxima tentativa
            if "quota" in str(e).lower() or "429" in str(e):
                logger.warning("⚠️ Quota excedida - aumentando intervalo para 60s")
                self.sheets_write_interval = 60.0  # Aumenta intervalo se quota excedida

    def get_current_count(self):
        return len(self.current_people)
    
    def get_total_detected(self):
        return self.total_people_detected

    def get_status(self):
        """Retorna status completo do radar"""
        status = {
            'id': self.radar_id,
            'name': self.radar_name,
            'area_tipo': self.area_tipo,
            'port': self.port,
            'running': self.is_running,
            'connected': self.serial_connection and self.serial_connection.is_open if self.serial_connection else False,
            'description': self.description,
            'current_count': self.get_current_count(),
            'total_detected': self.get_total_detected(),
            'max_simultaneous': self.max_simultaneous_people,
            'entries_count': self.entries_count,
            'exits_count': self.exits_count,
            'unique_people': len(self.unique_people_today),
            'people_in_area': len(self.current_people),
            'session_duration': (datetime.now() - self.session_start_time).total_seconds()
        }
        status['timestamp'] = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
        status['last_debug'] = getattr(self, 'last_debug', '')
        return status

class GravataDualRadarSystem:
    def __init__(self):
        self.radars = []
        self.gsheets_manager = None
        self.is_running = False

    def detect_available_ports(self):
        """Detecta portas seriais disponíveis"""
        ports = list(serial.tools.list_ports.comports())
        available_ports = []
        
        logger.info("🔍 Detectando portas seriais...")
        for port in ports:
            logger.info(f"   📡 {port.device} - {port.description}")
            available_ports.append(port.device) 
        
        return available_ports

    def initialize(self):
        """Inicializa o sistema dual radar"""
        try:
            # Detecta portas disponíveis
            available_ports = self.detect_available_ports()
            
            if len(available_ports) < 2:
                logger.error(f"❌ Necessário 2 portas, encontradas {len(available_ports)}")
                logger.info("💡 Conecte 2 dispositivos radar antes de prosseguir")
                return False
            
            # Ajusta configurações de porta se necessário
            for i, config in enumerate(RADAR_CONFIGS):
                if config['port'] not in available_ports:
                    if i < len(available_ports):
                        new_port = available_ports[i]
                        logger.warning(f"⚠️ Porta {config['port']} não encontrada, usando {new_port}")
                        config['port'] = new_port
                    else:
                        logger.error(f"❌ Não há portas suficientes para {config['id']}")
                        return False
            
            # Configura Google Sheets (compartilhado)
            script_dir = os.path.dirname(os.path.abspath(__file__))
            credentials_file = os.path.join(script_dir, CREDENTIALS_FILE)
            
            if not os.path.exists(credentials_file):
                logger.error(f"❌ Credenciais não encontradas: {credentials_file}")
                return False
            
            # Usa ID da primeira configuração (ambos usam a mesma planilha)
            spreadsheet_id = RADAR_CONFIGS[0]['spreadsheet_id']
            
            self.gsheets_manager = GoogleSheetsManager(
                credentials_file,
                spreadsheet_id,
                'GRAVATA_DUAL'
            )
            
            # Inicializa radares
            for config in RADAR_CONFIGS:
                radar = SingleRadarCounter(config)
                self.radars.append(radar)
            
            logger.info("✅ Sistema Dual Radar Gravatá inicializado!")
            return True
            
        except Exception as e:
            logger.error(f"❌ Erro na inicialização: {e}")
            return False

    def start(self):
        """Inicia ambos os radares"""
        try:
            if not self.gsheets_manager:
                logger.error("❌ Sistema não inicializado")
                return False
            
            # Inicia cada radar
            failed_radars = []
            for radar in self.radars:
                if not radar.start(self.gsheets_manager):
                    failed_radars.append(radar.radar_id)
            
            if failed_radars:
                logger.error(f"❌ Falha ao iniciar radares: {failed_radars}")
                return False
            
            self.is_running = True
            logger.info("🚀 Sistema Dual Radar Gravatá ATIVO!")
            return True
            
        except Exception as e:
            logger.error(f"❌ Erro ao iniciar sistema: {e}")
            return False

    def stop(self):
        """Para todos os radares"""
        self.is_running = False
        
        for radar in self.radars:
            radar.stop()
        
        logger.info("🛑 Sistema Dual Radar Gravatá parado!")

    def get_status(self):
        """Status de ambos os radares"""
        status = {
            'system_running': self.is_running,
            'radars': []
        }
        
        for radar in self.radars:
            status['radars'].append(radar.get_status())
        
        return status

def list_available_ports():
    """Lista todas as portas seriais disponíveis"""
    ports = list(serial.tools.list_ports.comports())
    
    print("\n🔍 DIAGNÓSTICO DE PORTAS SERIAIS - GRAVATÁ DUAL")
    print("=" * 60)
    
    if not ports:
        print("❌ Nenhuma porta serial encontrada!")
        return []
    
    print(f"✅ {len(ports)} porta(s) encontrada(s):")
    
    for i, port in enumerate(ports, 1):
        print(f"\n📡 Porta {i}:")
        print(f"   Dispositivo: {port.device}")
        print(f"   Descrição: {port.description}")
        print(f"   Fabricante: {port.manufacturer or 'N/A'}")
        
        desc_lower = port.description.lower()
        if any(term in desc_lower for term in 
               ['usb', 'serial', 'uart', 'cp210', 'ch340', 'ft232', 'arduino', 'esp32', 'modem']):
            print(f"   🎯 ADEQUADA para radar")
        else:
            print(f"   ⚠️ Pode não ser adequada")
    
    print("\n" + "=" * 60)
    return [port.device for port in ports]

def print_dual_status(radar_interna, radar_externa):
    """Exibe status das duas áreas lado a lado no terminal"""
    os.system('clear')
    status_int = radar_interna.get_status()
    status_ext = radar_externa.get_status()
    
    print(f"{'🔵 GRAVATÁ INTERNA':<40} | {'🔴 GRAVATÁ EXTERNA':<40}")
    print(f"{'='*38:<40} | {'='*38:<40}")
    print(f"{status_int['timestamp'] if 'timestamp' in status_int else '':<40} | {status_ext['timestamp'] if 'timestamp' in status_ext else '' :<40}")
    print(f"{status_int['id']} | 👥 {status_int['current_count']} ativas{'':<24} | {status_ext['id']} | 👥 {status_ext['current_count']} ativas")
    print(f"Entradas: {status_int['entries_count']} | Saídas: {status_int['exits_count']:<10} | Entradas: {status_ext['entries_count']} | Saídas: {status_ext['exits_count']}")
    print(f"Total: {status_int['total_detected']} | Máx: {status_int['max_simultaneous']:<12} | Total: {status_ext['total_detected']} | Máx: {status_ext['max_simultaneous']}")
    print(f"{'='*38:<40} | {'='*38:<40}")
    print()
    print(f"Debug interna: {status_int.get('last_debug', '')}")
    print(f"Debug externa: {status_ext.get('last_debug', '')}")
    print()

def main():
    """Função principal do sistema dual radar Gravatá"""
    logger.info("🚀 Inicializando Sistema DUAL RADAR GRAVATÁ (painel duplo)...")
    available_ports = list_available_ports()
    if len(available_ports) < 2:
        logger.error("❌ Sistema dual necessita 2 portas seriais!")
        logger.info("💡 Conecte 2 dispositivos radar USB")
        return
    system = GravataDualRadarSystem()
    try:
        if not system.initialize():
            logger.error("❌ Falha na inicialização")
            return
        if not system.start():
            logger.error("❌ Falha ao iniciar sistema")
            return
        radar_interna = None
        radar_externa = None
        for radar in system.radars:
            if radar.area_tipo == 'INTERNA':
                radar_interna = radar
            elif radar.area_tipo == 'EXTERNA':
                radar_externa = radar
        if not radar_interna or not radar_externa:
            logger.error("❌ Não encontrou ambos radares INTERNA e EXTERNA!")
            return
        # Loop principal
        while True:
            print_dual_status(radar_interna, radar_externa)
            time.sleep(2)
    except KeyboardInterrupt:
        logger.info("🛑 Encerrando por solicitação do usuário...")
    except Exception as e:
        logger.error(f"❌ Erro inesperado: {str(e)}")
        logger.error(traceback.format_exc())
    finally:
        system.stop()
        logger.info("✅ Sistema Dual Radar Gravatá encerrado!")

if __name__ == "__main__":
    main() 
