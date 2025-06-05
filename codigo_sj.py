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
        logging.FileHandler('single_radar_counter.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('single_radar_counter')

# Configurando o nível de log para outros módulos
logging.getLogger('urllib3').setLevel(logging.WARNING)
logging.getLogger('gspread').setLevel(logging.WARNING)

load_dotenv()

# Configuração do radar multi-pessoa v4.2
RADAR_CONFIG = {
    'id': 'RADAR_1',
    'name': 'Contador de Pessoas',
    'port': '/dev/cu.usbmodem1101',  # Porta correta do radar
    'baudrate': 115200,
    'spreadsheet_id': '1zVVyL6D9XSrzFvtDxaGJ-3CdniD-gG3Q-bUUXyqr3D4',  # Sua planilha
    'color': '🔴',
    'description': 'Contador v4.2: multi-pessoa simultânea, 8.3Hz, até 8 pessoas'
}

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
            logger.info(f"✅ Planilha conectada: {self.spreadsheet.title}")
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
        """Configura cabeçalhos da planilha simplificada (campos essenciais)"""
        try:
            headers = self.worksheet.row_values(1)
            # Apenas campos ESSENCIAIS para contagem de pessoas
            expected_headers = [
                'radar_id',           # ID do radar
                'timestamp',          # Data/hora
                'person_count',       # Pessoas simultâneas 
                'person_id',          # ID da pessoa
                'zone',               # Zona (PROXIMA/MEDIA/DISTANTE)
                'distance',           # Distância (metros)
                'confidence',         # Confiança da detecção (%)
                'total_detected',     # Total acumulativo
                'max_simultaneous'    # Máximo simultâneo
            ]
            
            if not headers or len(headers) < 9:
                logger.info("🔧 Configurando cabeçalhos simplificados (9 campos essenciais)")
                self.worksheet.clear()
                self.worksheet.append_row(expected_headers)
            else:
                logger.info("✅ Cabeçalhos simplificados verificados")
                    
        except Exception as e:
            logger.warning(f"⚠️ Erro ao configurar cabeçalhos: {e}")

class ZoneManager:
    def __init__(self):
        self.ZONE_1_DISTANCE = 2.0  # Zona próxima
        self.ZONE_2_DISTANCE = 4.0  # Zona média
        
    def get_zone(self, x, y):
        """Determinar zona baseada na distância"""
        distance = self.get_distance(x, y)
        
        if distance <= self.ZONE_1_DISTANCE:
            return 'PROXIMA'
        elif distance <= self.ZONE_2_DISTANCE:
            return 'MEDIA'
        else:
            return 'DISTANTE'
    
    def get_distance(self, x, y):
        """Calcular distância do radar"""
        import math
        return math.sqrt(x**2 + y**2)

class SingleRadarCounter:
    def __init__(self, config):
        self.config = config
        self.radar_id = config['id']
        self.radar_name = config['name']
        self.port = config['port']
        self.baudrate = config['baudrate']
        self.color = config['color']
        self.description = config['description']
        
        self.serial_connection = None
        self.is_running = False
        self.receive_thread = None
        self.gsheets_manager = None
        self.zone_manager = ZoneManager()
        
        # Sistema robusto de contagem de pessoas
        self.current_people = {}                # Pessoas atualmente na área {id: info}
        self.previous_people = {}               # Pessoas na iteração anterior
        self.people_history = {}                # Histórico completo {id: first_seen_time}
        self.total_people_detected = 0          # Total acumulativo REAL
        self.max_simultaneous_people = 0        # Máximo de pessoas simultâneas
        self.session_start_time = datetime.now()
        
        # Configurações de tracking
        self.exit_timeout = 3.0                 # Segundos para considerar que pessoa saiu
        self.reentry_timeout = 10.0             # Segundos para considerar nova entrada da mesma pessoa
        self.last_update_time = time.time()
        
        # Controle de escrita no Google Sheets (ANTI-QUOTA EXCEEDED)
        self.last_sheets_write = 0              # Último envio para planilha
        self.sheets_write_interval = 30.0       # Escreve apenas a cada 30 segundos
        self.pending_data = []                  # Buffer de dados pendentes
        
        # Estatísticas detalhadas
        self.entries_count = 0                  # Quantas pessoas entraram
        self.exits_count = 0                    # Quantas pessoas saíram
        self.unique_people_today = set()        # IDs únicos detectados hoje

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
                    timeout=2,  # Aumentado para 2 segundos
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
                wait_time = (attempt + 1) * 2  # Backoff exponencial
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
        
        logger.info(f"{self.color} 🚀 Radar iniciado com sucesso!")
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
        
        logger.info(f"{self.color} 🛑 Radar parado!")

    def receive_data_loop(self):
        """Loop principal de recebimento de dados com reconexão robusta"""
        import sys
        import os
        buffer = ""
        consecutive_errors = 0
        max_consecutive_errors = 5
        
        logger.info(f"{self.color} 🔄 Loop de dados iniciado...")
        
        while self.is_running:
            try:
                # Verifica se a conexão está ativa
                if not self.serial_connection or not self.serial_connection.is_open:
                    logger.warning(f"{self.color} ⚠️ Conexão perdida, tentando reconectar...")
                    if self.connect():
                        consecutive_errors = 0  # Reset contador de erros
                        buffer = ""  # Limpa buffer
                        continue
                    else:
                        consecutive_errors += 1
                        time.sleep(5)  # Aguarda mais tempo se falhou a reconexão
                        continue
                
                # Tenta ler dados
                in_waiting = self.serial_connection.in_waiting or 0
                data = self.serial_connection.read(in_waiting or 1)
                
                if data:
                    consecutive_errors = 0  # Reset contador se recebeu dados
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
                    # Força reconexão imediata
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
                
                # Se muitos erros consecutivos, pausa mais
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
        """Converte timestamp de milissegundos para formato brasileiro aprimorado"""
        try:
            # SEMPRE usa tempo atual para evitar problemas com timestamp do Arduino
            dt = datetime.now()
            
            # Formato brasileiro completo: DD/MM/AAAA HH:MM:SS
            return dt.strftime('%d/%m/%Y %H:%M:%S')
        except Exception as e:
            # Em caso de erro, retorna tempo atual
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
        
        # IGNORA person_id do Arduino (não é confiável) - usa posição + distância
        # Cria IDs únicos baseados em posição e características estáveis
        current_people_dict = {}
        
        for i, person in enumerate(active_people):
            # Cria ID único baseado em posição estável (não no ID do Arduino)
            x_pos = person.get('x_pos', 0)
            y_pos = person.get('y_pos', 0) 
            distance = person.get('distance_smoothed', person.get('distance_raw', 0))
            zone = person.get('zone', 'DESCONHECIDA')
            
            # ID baseado na posição arredondada (estável para pessoa parada)
            stable_id = f"P_{zone}_{distance:.1f}_{i}"
            
            # Procura se já existe pessoa similar (mesma zona, distância similar)
            found_existing = None
            for existing_id, existing_person in self.current_people.items():
                existing_dist = existing_person.get('distance_smoothed', 0)
                existing_zone = existing_person.get('zone', '')
                
                # Se pessoa está na mesma zona e distância similar (±0.3m), é a mesma
                if (existing_zone == zone and 
                    abs(existing_dist - distance) < 0.3):
                    found_existing = existing_id
                    break
            
            # Se encontrou pessoa similar, mantém ID existente
            if found_existing:
                current_people_dict[found_existing] = person
                current_people_dict[found_existing]['last_seen'] = current_time
            else:
                # Nova pessoa detectada
                person['first_seen'] = current_time
                person['last_seen'] = current_time
                current_people_dict[stable_id] = person
        
        # Detecta ENTRADAS REAIS (novas pessoas que não existiam)
        new_entries = []
        for person_id, person_info in current_people_dict.items():
            if person_id not in self.current_people:
                # Verifica se não é pessoa que acabou de sair (evita flickering)
                is_really_new = True
                for old_id, old_person in self.previous_people.items():
                    old_zone = old_person.get('zone', '')
                    old_dist = old_person.get('distance_smoothed', 0)
                    new_zone = person_info.get('zone', '')
                    new_dist = person_info.get('distance_smoothed', 0)
                    
                    # Se pessoa muito similar saiu recentemente, não conta como nova
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
                    logger.info(f"🆕 ENTRADA REAL: {zone} {dist:.1f}m (Total: {self.total_people_detected})")
        
        # Detecta SAÍDAS REAIS (pessoas que realmente saíram)
        exits = []
        for person_id, person_info in self.current_people.items():
            if person_id not in current_people_dict:
                # Pessoa saiu apenas se não foi detectada por tempo suficiente
                last_seen = person_info.get('last_seen', 0)
                if (current_time - last_seen) > 1.0:  # 1 segundo de timeout
                    exits.append(person_id)
                    self.exits_count += 1
                    zone = person_info.get('zone', 'DESCONHECIDA')
                    dist = person_info.get('distance_smoothed', 0)
                    logger.info(f"🚪 SAÍDA REAL: {zone} {dist:.1f}m (Entradas: {self.entries_count}, Saídas: {self.exits_count})")
        
        # Atualiza estado
        self.previous_people = self.current_people.copy()
        self.current_people = current_people_dict
        
        # Atualiza máximo simultâneo
        current_simultaneous = len(current_people_dict)
        if current_simultaneous > self.max_simultaneous_people:
            self.max_simultaneous_people = current_simultaneous
            logger.info(f"📊 NOVO MÁXIMO SIMULTÂNEO: {self.max_simultaneous_people} pessoas")
        
        # Log apenas se houve mudanças reais
        if new_entries or exits:
            logger.info(f"📊 STATUS CORRIGIDO: {current_simultaneous} ativas | {self.total_people_detected} total real | Máx: {self.max_simultaneous_people}")
        
        self.last_update_time = current_time

    def process_json_data(self, data_json):
        """Processa dados JSON multi-pessoa v4.2 recebidos do radar"""
        try:
            radar_id = data_json.get("radar_id", self.radar_id)
            timestamp_ms = data_json.get("timestamp_ms", 0)
            person_count = data_json.get("person_count", 0)
            active_people = data_json.get("active_people", [])
            tracking_method = data_json.get("tracking_method", "hybrid_multi")
            session_duration_ms = data_json.get("session_duration_ms", 0)
            update_rate_hz = data_json.get("update_rate_hz", 8.3)
            
            # IGNORA dados de contagem do Arduino (não são confiáveis para eventos)
            # Arduino envia IDs baseados em timestamp/contador interno, não pessoas reais
            # Vamos usar APENAS nossa lógica Python baseada em posição e movimento real
            
            # Converte timestamp para formato legível
            formatted_timestamp = self.convert_timestamp(timestamp_ms)
            
            # Atualiza contadores locais também
            self.update_people_count(person_count, active_people)
            
            # Limpa o terminal e mostra dados em tempo real simplificados
            os.system('clear')
            print(f"\n{self.color} ═══ CONTADOR ROBUSTO DE PESSOAS - TRACKING AVANÇADO ═══")
            print(f"⏰ {formatted_timestamp}")
            print(f"📡 {radar_id} | 👥 ATIVAS: {person_count}")
            print(f"🎯 TOTAL DETECTADAS: {self.total_people_detected} | 📊 MÁXIMO SIMULTÂNEO: {self.max_simultaneous_people}")
            print(f"🔄 ENTRADAS: {self.entries_count} | 🚪 SAÍDAS: {self.exits_count}")
            print(f"🆔 PESSOAS ÚNICAS: {len(self.unique_people_today)}")
            
            # Mostra duração da sessão
            session_duration = datetime.now() - self.session_start_time
            duration_str = self.format_duration(session_duration.total_seconds() * 1000)
            print(f"⏱️ SESSÃO: {duration_str}")
            
            # Status do envio para planilha (ANTI-QUOTA)
            pending_count = len(self.pending_data)
            time_since_last_send = time.time() - self.last_sheets_write
            next_send_in = max(0, self.sheets_write_interval - time_since_last_send)
            if pending_count > 0:
                print(f"📋 BUFFER: {pending_count} linhas | ⏳ Próximo envio em: {next_send_in:.0f}s")
            else:
                print(f"📋 PLANILHA: Sincronizada ✅")
            
            if active_people and len(active_people) > 0:
                print(f"\n👥 PESSOAS DETECTADAS AGORA ({len(active_people)}):")
                print(f"{'Zona':<8} {'Dist(m)':<7} {'X,Y':<10} {'Conf%':<5} {'Status':<8} {'Desde':<8}")
                print("-" * 55)
                
                current_time = time.time()
                for i, person in enumerate(active_people):
                    zone = person.get("zone", "N/A")
                    confidence = person.get("confidence", 0)
                    distance_smoothed = person.get("distance_smoothed", 0)
                    x_pos = person.get("x_pos", 0)
                    y_pos = person.get("y_pos", 0)
                    stationary = person.get("stationary", False)
                    
                    # Encontra ID da nossa lógica interna
                    our_person_id = None
                    for internal_id, internal_person in self.current_people.items():
                        if (abs(internal_person.get('distance_smoothed', 0) - distance_smoothed) < 0.1 and
                            internal_person.get('zone', '') == zone):
                            our_person_id = internal_id
                            break
                    
                    # Calcula tempo desde primeira detecção (nossa lógica)
                    if our_person_id and our_person_id in self.current_people:
                        first_seen = self.current_people[our_person_id].get('first_seen', current_time)
                        time_in_area = current_time - first_seen
                        time_str = f"{time_in_area:.0f}s" if time_in_area < 60 else f"{time_in_area/60:.1f}m"
                    else:
                        time_str = "novo"
                    
                    # Status da pessoa
                    status = "Parado" if stationary else "Móvel"
                    pos_str = f"{x_pos:.1f},{y_pos:.1f}"
                    
                    print(f"{zone:<8} {distance_smoothed:<7.2f} {pos_str:<10} {confidence:<5}% {status:<8} {time_str:<8}")
                
                # Envia APENAS UM resumo por ciclo (não uma linha por pessoa)
                if self.gsheets_manager:
                    # Calcula dados agregados
                    avg_confidence = sum(p.get("confidence", 0) for p in active_people) / len(active_people)
                    zones_detected = list(set(p.get("zone", "N/A") for p in active_people))
                    zones_str = ",".join(sorted(zones_detected))
                    
                    # ID mais profissional baseado no contexto
                    if len(active_people) == 1:
                        person_description = "Pessoa Individual"
                    elif len(active_people) <= 3:
                        person_description = "Grupo Pequeno"
                    elif len(active_people) <= 10:
                        person_description = "Grupo Médio"
                    elif len(active_people) <= 20:
                        person_description = "Grupo Grande"
                    else:
                        person_description = "Multidão"
                    
                    row = [
                        radar_id,                          # 1. radar_id
                        formatted_timestamp,               # 2. timestamp
                        len(active_people),                # 3. person_count (real detectadas agora)
                        person_description,                # 4. person_id (descrição profissional)
                        zones_str,                         # 5. zone (todas as zonas ordenadas)
                        f"{sum(p.get('distance_smoothed', 0) for p in active_people) / len(active_people):.1f}",  # 6. distance (média)
                        f"{avg_confidence:.0f}",           # 7. confidence (média)
                        self.total_people_detected,       # 8. total_detected (nossa contagem real)
                        self.max_simultaneous_people      # 9. max_simultaneous (nosso máximo real)
                    ]
                    self.pending_data.append(row)
                
                print(f"\n💡 DETECTANDO {len(active_people)} pessoa(s) SIMULTANEAMENTE")
                
                # Estatísticas por zona
                zone_stats = {}
                high_confidence = 0
                for person in active_people:
                    zone = person.get("zone", "N/A")
                    zone_stats[zone] = zone_stats.get(zone, 0) + 1
                    if person.get("confidence", 0) >= 70:
                        high_confidence += 1
                
                if zone_stats:
                    print("📊 DISTRIBUIÇÃO POR ZONA:", end=" ")
                    for zone, count in zone_stats.items():
                        print(f"{zone}: {count}", end="  ")
                    print()
                
                print(f"✅ QUALIDADE: {high_confidence}/{len(active_people)} com alta confiança (≥70%)")
                
            else:
                print(f"\n👻 Nenhuma pessoa detectada no momento.")
                
                # Envia dados zerados apenas se houve mudança de estado
                if self.gsheets_manager and len(self.previous_people) > 0:
                    row = [
                        radar_id,                          # 1. radar_id
                        formatted_timestamp,               # 2. timestamp
                        0,                                 # 3. person_count (zero)
                        "Area_Vazia",                      # 4. person_id (indicador)
                        "VAZIA",                           # 5. zone 
                        "0",                               # 6. distance
                        "0",                               # 7. confidence
                        self.total_people_detected,       # 8. total_detected (nossa contagem real)
                        self.max_simultaneous_people      # 9. max_simultaneous (nosso máximo real)
                    ]
                    self.pending_data.append(row)
            
            print("\n" + "═" * 60)
            print("🎯 SISTEMA ROBUSTO: Detecta entradas/saídas precisamente")
            print("⚡ Pressione Ctrl+C para encerrar | Tracking Avançado Ativo")
            
            # Envia dados controladamente (ANTI-QUOTA EXCEEDED)
            self.send_pending_data_to_sheets()
            
        except Exception as e:
            logger.error(f"Erro ao processar dados JSON simplificados: {e}")
            logger.debug(f"JSON recebido: {data_json}")

    def send_pending_data_to_sheets(self):
        """Envia dados para Google Sheets de forma controlada (ANTI-QUOTA EXCEEDED)"""
        try:
            current_time = time.time()
            
            # Verifica se já passou tempo suficiente desde último envio
            if (current_time - self.last_sheets_write) < self.sheets_write_interval:
                return  # Ainda não é hora de enviar
            
            # Se não há dados pendentes, não faz nada
            if not self.pending_data or not self.gsheets_manager:
                return
            
            # Pega apenas os dados mais recentes (máximo 10 linhas por vez)
            data_to_send = self.pending_data[-10:] if len(self.pending_data) > 10 else self.pending_data
            
            # Envia em lote (mais eficiente)
            if data_to_send:
                logger.info(f"📊 Enviando {len(data_to_send)} linhas para Google Sheets...")
                
                # Envia todas as linhas de uma vez (batch)
                for row in data_to_send:
                    self.gsheets_manager.worksheet.append_row(row)
                    time.sleep(0.5)  # Pequena pausa entre linhas
                
                logger.info(f"✅ {len(data_to_send)} linhas enviadas com sucesso!")
                
                # Atualiza controles
                self.last_sheets_write = current_time
                self.pending_data = []  # Limpa dados enviados
                
        except Exception as e:
            logger.error(f"❌ Erro ao enviar dados para planilha: {e}")
            # Em caso de erro, mantém dados para próxima tentativa
            if "quota" in str(e).lower() or "429" in str(e):
                logger.warning("⚠️ Quota excedida - aumentando intervalo para 60s")
                self.sheets_write_interval = 60.0  # Aumenta intervalo se quota excedida

    def get_current_count(self):
        """Retorna o último person_count recebido"""
        return len(self.current_people)
    
    def get_total_detected(self):
        """Retorna total de pessoas detectadas na sessão"""
        return self.total_people_detected

    def get_status(self):
        """Retorna status completo do radar com estatísticas robustas"""
        return {
            'id': self.radar_id,
            'name': self.radar_name,
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

def list_available_ports():
    """Lista todas as portas seriais disponíveis para diagnóstico"""
    ports = list(serial.tools.list_ports.comports())
    
    print("\n🔍 DIAGNÓSTICO DE PORTAS SERIAIS")
    print("=" * 50)
    
    if not ports:
        print("❌ Nenhuma porta serial encontrada!")
        return []
    
    print(f"✅ {len(ports)} porta(s) encontrada(s):")
    
    for i, port in enumerate(ports, 1):
        print(f"\n📡 Porta {i}:")
        print(f"   Dispositivo: {port.device}")
        print(f"   Descrição: {port.description}")
        print(f"   Fabricante: {port.manufacturer or 'N/A'}")
        print(f"   VID:PID: {port.vid}:{port.pid}" if port.vid and port.pid else "   VID:PID: N/A")
        print(f"   Serial: {port.serial_number or 'N/A'}")
        
        # Identifica se é adequada para o radar
        desc_lower = port.description.lower()
        if any(term in desc_lower for term in 
               ['usb', 'serial', 'uart', 'cp210', 'ch340', 'ft232', 'arduino', 'esp32', 'jtag', 'modem']):
            print(f"   🎯 ADEQUADA para radar")
        else:
            print(f"   ⚠️ Pode não ser adequada para radar")
    
    print("\n" + "=" * 50)
    return [port.device for port in ports]

def main():
    """Função principal"""
    logger.info("🚀 Inicializando Contador de Pessoas Single Radar...")
    
    # Mostra diagnóstico de portas
    available_ports = list_available_ports()
    
    # Verifica se a porta configurada existe
    configured_port = RADAR_CONFIG['port']
    if configured_port in available_ports:
        logger.info(f"✅ Porta configurada {configured_port} está disponível")
    else:
        logger.warning(f"⚠️ Porta configurada {configured_port} NÃO está disponível")
        if available_ports:
            logger.info(f"💡 Portas disponíveis: {', '.join(available_ports)}")
            # Sugere primeira porta adequada
            for port_device in available_ports:
                for port in serial.tools.list_ports.comports():
                    if port.device == port_device:
                        desc_lower = port.description.lower()
                        if any(term in desc_lower for term in 
                               ['usb', 'serial', 'uart', 'modem']):
                            logger.info(f"💡 Sugestão: Tente usar a porta {port_device}")
                            break
                break
    
    # Configura Google Sheets
    script_dir = os.path.dirname(os.path.abspath(__file__))
    credentials_file = os.path.join(script_dir, 'serial_radar', 'credenciais.json')
    
    # Verifica se arquivo de credenciais existe
    if not os.path.exists(credentials_file):
        logger.error(f"❌ Arquivo de credenciais não encontrado: {credentials_file}")
        logger.info("💡 Crie a pasta 'serial_radar' e coloque o arquivo 'credenciais.json' nela")
        return
    
    try:
        gsheets_manager = GoogleSheetsManager(
            credentials_file, 
            RADAR_CONFIG['spreadsheet_id'],
            RADAR_CONFIG['id']
        )
        logger.info("✅ Google Sheets configurado")
    except Exception as e:
        logger.error(f"❌ Erro ao configurar Google Sheets: {e}")
        logger.info("💡 Verifique se o arquivo credenciais.json está correto e se o spreadsheet_id é válido")
        return
    
    # Inicializa radar
    radar = SingleRadarCounter(RADAR_CONFIG)
    
    try:
        # Inicia o radar
        logger.info("🔄 Tentando iniciar o radar...")
        if not radar.start(gsheets_manager):
            logger.error("❌ Falha ao iniciar o radar")
            logger.info("💡 Verifique:")
            logger.info("   - Se o dispositivo está conectado")
            logger.info("   - Se a porta está correta")
            logger.info("   - Se outro programa não está usando a porta")
            return
        
        # Exibe status inicial
        status = radar.get_status()
        logger.info("=" * 80)
        logger.info("👥 CONTADOR ROBUSTO DE PESSOAS - SISTEMA ESP32 v4.2 AVANÇADO")
        logger.info("=" * 80)
        logger.info(f"🔴 {status['name']}: {status['port']}")
        logger.info(f"📋 {status['description']}")
        logger.info("🚀 Sistema CORRIGIDO v4.3 - Tracking Preciso para Eventos:")
        logger.info("   • Lógica baseada em POSIÇÃO REAL (não IDs do Arduino)")
        logger.info("   • Detecção precisa de entrada/saída por zona")
        logger.info("   • Pessoas paradas contam apenas UMA vez")
        logger.info("   • Anti-flickering: evita contagem duplicada")
        logger.info("   • Contagem acumulativa REAL corrigida")
        logger.info("   • Ideal para eventos com muitas pessoas")
        logger.info("   • Tracking por zona + distância + posição")
        logger.info("   • Ignora dados não-confiáveis do Arduino")
        logger.info("⚡ Sistema ativo - Dados sendo enviados para Google Sheets")
        logger.info("🔄 Reconexão automática habilitada")
        logger.info("=" * 80)
        
        # Mantém o sistema rodando
        status_counter = 0
        while True:
            time.sleep(5)
            status_counter += 1
            
            # Status a cada 30 segundos (6 * 5s = 30s)
            if status_counter >= 6:
                status_counter = 0
                status = radar.get_status()
                current_count = status['people_in_area']
                total_detected = status['total_detected']
                max_simultaneous = status['max_simultaneous']
                entries = status['entries_count']
                exits = status['exits_count']
                unique_people = status['unique_people']
                
                if radar.is_running and radar.serial_connection and radar.serial_connection.is_open:
                    logger.info(f"📊 STATUS ROBUSTO: {current_count} ativas | {total_detected} total | {entries} entradas | {exits} saídas | {unique_people} únicas | Máx: {max_simultaneous}")
                elif radar.is_running:
                    logger.warning("⚠️ Radar rodando mas conexão perdida - tentando reconectar...")
                else:
                    logger.warning("⚠️ Radar não está ativo")
    
    except KeyboardInterrupt:
        logger.info("🛑 Encerrando por solicitação do usuário...")
    
    except Exception as e:
        logger.error(f"❌ Erro inesperado: {str(e)}")
        logger.error(traceback.format_exc())
    
    finally:
        radar.stop()
        logger.info("✅ Sistema encerrado!")

if __name__ == "__main__":
    main() 
