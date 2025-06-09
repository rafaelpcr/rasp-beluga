#!/usr/bin/env python3
"""
RADAR GRAVATA SIMPLIFICADO v1.0
Sistema mais eficaz usando valores diretos do Arduino
Foco na detecção precisa sem complexidade excessiva
Baseado nas otimizações do Santa Cruz
"""

import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
import logging
import os
import time
import json
import serial
import threading
import serial.tools.list_ports
import gc
from dotenv import load_dotenv

# Configuração de logging simples
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('gravata_simples.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('gravata_simples')

load_dotenv()

# ✅ CONFIGURAÇÃO PARA DOIS RADARES GRAVATA
RADAR_CONFIGS = {
    'EXTERNA': {
        'id': 'RADAR_GRAVATA_EXTERNA',
        'name': 'Gravata Área Externa',
        'port': '/dev/ttyUSB0',  # Radar da área externa (Raspberry Pi)
        'baudrate': 115200,
        'spreadsheet_id': '17KkL1rm1pCJ1Q57FAzyZKqR0lQyPqdiqCjO1mf1QKGQ',  # ID CORRIGIDO da planilha externa
        'color': '🔵',
        'area_tipo': 'AREA_EXTERNA',
        'description': 'Passagem e Interesse'
    },
    'INTERNA': {
        'id': 'RADAR_GRAVATA_INTERNA', 
        'name': 'Gravata Área Interna',
        'port': '/dev/ttyUSB1',  # Radar da área interna (Raspberry Pi - porta diferente)
        'baudrate': 115200,
        'spreadsheet_id': '1ACu8Qmicxv7Av-1nAK_dIDbcD_RJBizk2iXspixK2Gg',  # ID CORRIGIDO da planilha interna
        'color': '🟣',
        'area_tipo': 'AREA_INTERNA', 
        'description': 'Ativações Culturais'
    }
}

class SimpleGoogleSheetsManager:
    """Google Sheets Manager Simplificado para Gravata"""
    
    def __init__(self, creds_path, spreadsheet_id, radar_id):
        SCOPES = [
            'https://www.googleapis.com/auth/spreadsheets',
            'https://www.googleapis.com/auth/drive'
        ]
        self.radar_id = radar_id
        self.spreadsheet_id = spreadsheet_id
        self.last_successful_write = datetime.now()
        
        # Conecta
        self.creds = Credentials.from_service_account_file(creds_path, scopes=SCOPES)
        self.gc = gspread.authorize(self.creds)
        self.spreadsheet = self.gc.open_by_key(self.spreadsheet_id)
        self.worksheet = self.spreadsheet.get_worksheet(0)
        
        self._setup_headers()

    def _setup_headers(self):
        """Configura cabeçalhos corretos conforme planilha da área interna"""
        try:
            headers = self.worksheet.row_values(1)
            expected_headers = [
                'radar_id', 'timestamp', 'person_count', 'person_id', 
                'zone', 'distance', 'confidence', 'total_detected', 'max_simultaneous'
            ]
            
            if not headers or len(headers) < 9:
                logger.info("🔧 Configurando cabeçalhos corretos do Gravata...")
                self.worksheet.clear()
                self.worksheet.append_row(expected_headers)
        except Exception as e:
            logger.warning(f"⚠️ Erro configurando cabeçalhos: {e}")

    def append_row(self, row):
        """Envia linha com retry simples"""
        for attempt in range(2):
            try:
                self.worksheet.append_row(row)
                self.last_successful_write = datetime.now()
                return True
            except Exception as e:
                if attempt == 0:
                    logger.warning(f"⚠️ Erro envio, tentando novamente: {e}")
                    time.sleep(2)
                else:
                    logger.error(f"❌ Falha no envio: {e}")
                    return False
        return False

class SimpleZoneManager:
    """Sistema de zonas simplificado para Gravata - DUAS ÁREAS DISTINTAS"""
    
    def __init__(self):
        # ✅ GRAVATA REAL: Zonas corretas baseadas na distância
        self.ZONES = {
            'AREA_PASSAGEM': (0.0, 2.0),       # 0-2m - Passagem (área externa próxima)
            'AREA_INTERESSE': (2.0, 5.0),      # 2-5m - Interesse (área externa distante)
            'AREA_INTERNA': (5.0, 10.0)        # 5-10m - Ativações culturais (área interna)
        }
    
    def get_zone(self, distance):
        """Determina zona pela distância (Gravata com zonas corretas)"""
        for zone_name, (min_dist, max_dist) in self.ZONES.items():
            if min_dist <= distance < max_dist:
                return zone_name
        return 'FORA_ALCANCE'
    
    def get_zone_description(self, zone_name):
        """Descrição das zonas do Gravata"""
        descriptions = {
            'AREA_PASSAGEM': 'Área de Passagem (< 2m)',
            'AREA_INTERESSE': 'Área de Interesse (2-5m)', 
            'AREA_INTERNA': 'Área Interna - Ativações (5-10m)',
            'FORA_ALCANCE': 'Fora de Alcance'
        }
        return descriptions.get(zone_name, zone_name)

class SimpleRadarCounter:
    """Contador Gravata Simplificado e Eficaz"""
    
    def __init__(self, config):
        self.config = config
        self.radar_id = config['id']
        self.port = config['port']
        self.baudrate = config['baudrate']
        self.color = config['color']
        
        # Estado simplificado
        self.serial_connection = None
        self.is_running = False
        self.receive_thread = None
        self.gsheets_manager = None
        self.zone_manager = SimpleZoneManager()
        
        # Contadores eficazes
        self.current_people = {}
        self.total_people_detected = 0
        self.max_simultaneous_people = 0
        self.session_start_time = datetime.now()
        
        # Configurações de envio otimizadas
        self.last_sheets_write = 0
        self.sheets_write_interval = 30.0  # 30 segundos (mais responsivo)
        self.pending_data = []
        
        # Específico do Gravata (configuração dinâmica)
        self.area_tipo = config.get('area_tipo', 'AREA_EXTERNA')
        self.last_detection_time = time.time()

    def connect(self):
        """Conecta à porta serial de forma simples"""
        try:
            # Auto-detecta porta se necessário
            if not os.path.exists(self.port):
                detected_port = self.find_serial_port()
                if detected_port:
                    self.port = detected_port
                else:
                    logger.error("❌ Nenhuma porta serial encontrada")
                    return False
            
            logger.info(f"🔌 Conectando à porta {self.port}")
            
            self.serial_connection = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=2.0,
                write_timeout=2.0
            )
            
            time.sleep(3)  # Aguarda estabilização
            
            if self.serial_connection.is_open:
                logger.info(f"✅ Conectado com sucesso!")
                return True
                
        except Exception as e:
            logger.error(f"❌ Erro na conexão: {e}")
            
        return False

    def find_serial_port(self):
        """Detecta porta serial automaticamente"""
        ports = list(serial.tools.list_ports.comports())
        
        for port in ports:
            desc_lower = port.description.lower()
            # Inclui usbmodem para macOS
            if (any(term in desc_lower for term in
                  ['usb', 'serial', 'arduino', 'esp32', 'cp210', 'ch340']) or 
                'usbmodem' in port.device):
                logger.info(f"🔍 Porta detectada: {port.device}")
                return port.device
        
        return None

    def start(self, gsheets_manager):
        """Inicia o radar"""
        self.gsheets_manager = gsheets_manager
        
        if not self.connect():
            return False
        
        self.is_running = True
        self.receive_thread = threading.Thread(target=self.receive_data_loop, daemon=True)
        self.receive_thread.start()
        
        logger.info(f"🚀 Gravata simplificado iniciado!")
        return True

    def stop(self):
        """Para o radar"""
        self.is_running = False
        
        if self.serial_connection:
            try:
                self.serial_connection.close()
            except:
                pass
        
        logger.info("🛑 Gravata parado!")

    def receive_data_loop(self):
        """Loop de recebimento simplificado"""
        buffer = ""
        
        while self.is_running:
            try:
                if not self.serial_connection or not self.serial_connection.is_open:
                    logger.warning("⚠️ Conexão perdida, tentando reconectar...")
                    if self.connect():
                        buffer = ""
                        continue
                    else:
                        time.sleep(5)
                        continue
                
                # Lê dados disponíveis
                if self.serial_connection.in_waiting > 0:
                    data = self.serial_connection.read(self.serial_connection.in_waiting)
                    text = data.decode('utf-8', errors='ignore')
                    buffer += text
                    
                    # Processa linhas completas
                    if '\n' in buffer:
                        lines = buffer.split('\n')
                        buffer = lines[-1]
                        
                        for line in lines[:-1]:
                            line = line.strip()
                            if line.startswith('{'):
                                try:
                                    data_json = json.loads(line)
                                    self.process_json_data(data_json)
                                except json.JSONDecodeError:
                                    logger.debug(f"JSON inválido: {line[:50]}...")
                
                time.sleep(0.1)
                
            except Exception as e:
                logger.error(f"❌ Erro no loop: {e}")
                time.sleep(2)

    def process_json_data(self, data_json):
        """Processa dados JSON de forma simplificada e eficaz"""
        try:
            radar_id = data_json.get("radar_id", self.radar_id)
            timestamp_ms = data_json.get("timestamp_ms", 0)
            person_count = data_json.get("person_count", 0)
            active_people = data_json.get("active_people", [])
            
            # Timestamp atual
            formatted_timestamp = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
            
            # ✅ TRACKING SIMPLIFICADO MAS EFICAZ
            self.update_people_tracking(active_people)
            
            # ✅ DISPLAY LIMPO E INFORMATIVO
            if os.getenv('TERM'):
                os.system('clear')
            
            print(f"\n{self.color} ═══ GRAVATA SIMPLIFICADO E EFICAZ ═══")
            print(f"⏰ {formatted_timestamp}")
            print(f"🏪 {radar_id} | 👥 PESSOAS ATIVAS: {len(active_people)}")
            print(f"🎯 TOTAL DETECTADAS: {self.total_people_detected}")
            print(f"📊 MÁXIMO SIMULTÂNEO: {self.max_simultaneous_people}")
            print(f"🏷️ ÁREA: {self.area_tipo}")
            
            # Runtime
            runtime = datetime.now() - self.session_start_time
            runtime_str = f"{runtime.total_seconds()/60:.1f}min"
            print(f"⏱️ SESSÃO: {runtime_str}")
            
            # Status da planilha
            pending_count = len(self.pending_data)
            if pending_count > 0:
                print(f"📋 BUFFER: {pending_count} linhas | ⏳ Enviando a cada 30s")
            else:
                print(f"📋 PLANILHA: Sincronizada ✅")
            
            if active_people:
                print(f"\n👥 DETECÇÕES ATUAIS ({len(active_people)}):")
                print(f"{'#':<2} {'Distância':<10} {'Zona':<18} {'Confiança':<10}")
                print("-" * 50)
                
                distances = []
                zones = []
                confidences = []
                
                for i, person in enumerate(active_people):
                    # ✅ USA DIRETAMENTE OS VALORES DO ARDUINO (sem cálculos extras)
                    distance = person.get("distance_raw", 0)
                    confidence = person.get("confidence", 85)
                    
                    # ✅ ZONA SIMPLIFICADA BASEADA APENAS EM DISTÂNCIA
                    zone = self.zone_manager.get_zone(distance)
                    zone_desc = self.zone_manager.get_zone_description(zone)
                    
                    print(f"{i+1:<2} {distance:<10.2f} {zone_desc:<18} {confidence:<10}%")
                    
                    distances.append(distance)
                    zones.append(zone)
                    confidences.append(confidence)
                
                # ✅ PREPARA DADOS PARA PLANILHA (simplificado)
                if self.gsheets_manager:
                    avg_distance = sum(distances) / len(distances)
                    avg_confidence = sum(confidences) / len(confidences)
                    zones_str = ",".join(sorted(set(zones)))
                    distances_str = ",".join([f"{d:.1f}" for d in distances])
                    
                    # ✅ FORMATO CORRETO: 9 colunas conforme planilha interna
                    row = [
                        radar_id,                           # radar_id
                        formatted_timestamp,                # timestamp  
                        len(active_people),                 # person_count
                        f"Pessoa_{len(active_people)}",     # person_id
                        zones_str,                          # zone (zona principal)
                        f"{sum(distances)/len(distances):.1f}",  # distance (média)
                        f"{avg_confidence:.0f}",            # confidence
                        self.total_people_detected,         # total_detected
                        self.max_simultaneous_people        # max_simultaneous
                    ]
                    
                    self.pending_data.append(row)
                    logger.info(f"📋 Dados adicionados: {len(active_people)} pessoas detectadas")
                
                print(f"\n🏢 ANÁLISE {self.area_tipo}:")
                print(f"   • Distância média: {sum(distances)/len(distances):.1f}m")
                print(f"   • Confiança média: {sum(confidences)/len(confidences):.0f}%")
                print(f"   • Zonas ativas: {', '.join(set(self.zone_manager.get_zone_description(z) for z in zones))}")
                
                # Análise específica por área
                if self.area_tipo == 'AREA_EXTERNA':
                    passagem = sum(1 for d in distances if d < 2.0)
                    interesse = sum(1 for d in distances if 2.0 <= d < 5.0)
                    print(f"   • 🚶 {passagem} pessoa(s) em passagem (< 2m)")
                    print(f"   • 👀 {interesse} pessoa(s) com interesse (2-5m)")
                elif self.area_tipo == 'AREA_INTERNA':
                    ativacoes = sum(1 for d in distances if d >= 5.0)
                    print(f"   • 🎨 {ativacoes} pessoa(s) nas ativações culturais (5-10m)")
                
            else:
                area_desc = "área externa" if self.area_tipo == 'AREA_EXTERNA' else "área interna"
                print(f"\n👻 Nenhuma pessoa detectada na {area_desc}")
                
                # Envia dados zerados se mudou de estado
                if self.gsheets_manager and hasattr(self, 'last_person_count'):
                    if getattr(self, 'last_person_count', 0) > 0:
                        # ✅ FORMATO CORRETO: 9 colunas quando área vazia
                        row = [
                            radar_id,                       # radar_id
                            formatted_timestamp,            # timestamp
                            0,                              # person_count
                            "Nenhuma",                      # person_id
                            f"{self.area_tipo}_VAZIA",      # zone
                            "0.0",                          # distance
                            "0",                            # confidence
                            self.total_people_detected,     # total_detected
                            self.max_simultaneous_people    # max_simultaneous
                        ]
                        self.pending_data.append(row)
                        logger.info(f"📋 {area_desc} vazia detectada")
            
            # Armazena último count para detectar mudanças
            setattr(self, 'last_person_count', len(active_people))
            
            print("\n" + "=" * 55)
            print("🔵 GRAVATA SIMPLIFICADO E EFICAZ")
            print("✅ Usa valores diretos do Arduino")  
            print("✅ Zonas baseadas em distância da gôndola")
            print("✅ Tracking preciso e simples")
            print("✅ Análise específica de loja")
            print("✅ Envio otimizado (30s intervalo)")
            print("⚡ Pressione Ctrl+C para encerrar")
            
            # ✅ ENVIA DADOS PARA PLANILHA
            self.send_pending_data()
            
        except Exception as e:
            logger.error(f"❌ Erro processando JSON: {e}")

    def update_people_tracking(self, active_people):
        """Sistema de tracking simplificado mas preciso para Gravata"""
        current_time = time.time()
        
        # ✅ LÓGICA SIMPLIFICADA: conta pessoas novas por distância única
        current_distances = set()
        
        for person in active_people:
            distance = person.get("distance_raw", 0)
            # Agrupa por distância (arredondada para evitar micro-variações)
            rounded_distance = round(distance, 1)
            current_distances.add(rounded_distance)
        
        # ✅ DETECTA NOVAS PESSOAS (distâncias que não existiam antes)
        previous_distances = getattr(self, 'last_distances', set())
        new_distances = current_distances - previous_distances
        
        if new_distances:
            new_count = len(new_distances)
            self.total_people_detected += new_count
            area_desc = "área externa" if self.area_tipo == 'AREA_EXTERNA' else "área interna"
            logger.info(f"🆕 {new_count} nova(s) pessoa(s) detectada(s) na {area_desc}!")
        
        # ✅ ATUALIZA MÁXIMO SIMULTÂNEO
        current_count = len(active_people)
        if current_count > self.max_simultaneous_people:
            self.max_simultaneous_people = current_count
            area_desc = "área externa" if self.area_tipo == 'AREA_EXTERNA' else "área interna"
            logger.info(f"📊 Novo máximo simultâneo na {area_desc}: {current_count} pessoas")
        
        # Armazena para próxima comparação
        setattr(self, 'last_distances', current_distances)
        self.last_detection_time = current_time

    def send_pending_data(self):
        """Envia dados para planilha de forma otimizada"""
        try:
            current_time = time.time()
            
            # Verifica intervalo
            if (current_time - self.last_sheets_write) < self.sheets_write_interval:
                return
            
            if not self.pending_data or not self.gsheets_manager:
                return
            
            # Envia todas as linhas pendentes
            if self.pending_data:
                logger.info(f"📊 Enviando {len(self.pending_data)} linhas do Gravata...")
                
                for row in self.pending_data:
                    success = self.gsheets_manager.append_row(row)
                    if not success:
                        logger.warning("⚠️ Falha no envio, tentando na próxima")
                        return
                    time.sleep(0.3)  # Pausa entre linhas
                
                logger.info(f"✅ {len(self.pending_data)} linhas do Gravata enviadas!")
                self.last_sheets_write = current_time
                self.pending_data = []  # Limpa buffer
                
        except Exception as e:
            logger.error(f"❌ Erro no envio: {e}")

    def get_status(self):
        """Status simplificado do Gravata"""
        return {
            'id': self.radar_id,
            'running': self.is_running,
            'connected': bool(self.serial_connection and self.serial_connection.is_open),
            'total_detected': self.total_people_detected,
            'max_simultaneous': self.max_simultaneous_people,
            'area_tipo': self.area_tipo,
            'session_duration': (datetime.now() - self.session_start_time).total_seconds()
        }

def test_sheets_access():
    """Testa acesso às planilhas antes de iniciar os radares"""
    logger.info("🧪 Testando acesso às planilhas...")
    
    script_dir = os.path.dirname(os.path.abspath(__file__))
    credentials_file = os.path.join(script_dir, 'serial_radar', 'credenciais.json')
    
    if not os.path.exists(credentials_file):
        logger.error(f"❌ Credenciais não encontradas: {credentials_file}")
        return False
    
    success_count = 0
    for area, config in RADAR_CONFIGS.items():
        try:
            logger.info(f"🔍 Testando planilha {area}...")
            manager = SimpleGoogleSheetsManager(
                credentials_file,
                config['spreadsheet_id'], 
                config['id']
            )
            logger.info(f"✅ Planilha {area} acessível!")
            success_count += 1
        except Exception as e:
            logger.error(f"❌ Erro acessando planilha {area}: {e}")
            logger.error("🔧 Verificar se a conta de serviço tem acesso:")
            logger.error(f"   Email: projetobeluga@codigorasp.iam.gserviceaccount.com")
            logger.error(f"   Planilha ID: {config['spreadsheet_id']}")
    
    logger.info(f"📊 Resultado: {success_count}/{len(RADAR_CONFIGS)} planilhas acessíveis")
    return success_count > 0

def main():
    """Função principal para DOIS RADARES GRAVATA simultâneos"""
    logger.info("🚀 Iniciando Sistema Gravata Dual (Área Externa + Interna)...")
    
    if not test_sheets_access():
        return
    
    # Google Sheets
    script_dir = os.path.dirname(os.path.abspath(__file__))
    credentials_file = os.path.join(script_dir, 'serial_radar', 'credenciais.json')
    
    if not os.path.exists(credentials_file):
        logger.error(f"❌ Credenciais não encontradas: {credentials_file}")
        return
    
    # ✅ CONFIGURAÇÃO DUAL - DOIS RADARES
    radares = {}
    gsheets_managers = {}
    
    for area, config in RADAR_CONFIGS.items():
        try:
            # Cria manager específico para cada área
            gsheets_managers[area] = SimpleGoogleSheetsManager(
                credentials_file, 
                config['spreadsheet_id'],
                config['id']
            )
            logger.info(f"✅ Google Sheets configurado para {area}")
            
            # Cria radar para cada área
            radares[area] = SimpleRadarCounter(config)
            
        except Exception as e:
            logger.error(f"❌ Erro configurando {area}: {e}")
            return
    
    # ✅ INICIA AMBOS OS RADARES
    radares_ativos = {}
    
    for area, radar in radares.items():
        try:
            if radar.start(gsheets_managers[area]):
                radares_ativos[area] = radar
                logger.info(f"✅ Radar {area} iniciado com sucesso!")
            else:
                logger.error(f"❌ Falha ao iniciar radar {area}")
        except Exception as e:
            logger.error(f"❌ Erro iniciando radar {area}: {e}")
    
    if not radares_ativos:
        logger.error("❌ Nenhum radar foi iniciado com sucesso")
        return
    
    try:
        logger.info("=" * 60)
        logger.info("🔵 SISTEMA GRAVATA DUAL v1.0")
        logger.info("=" * 60)
        logger.info("🎯 CARACTERÍSTICAS:")
        logger.info("   ✅ DOIS RADARES simultâneos")
        logger.info("   ✅ Área Externa: Passagem e interesse")
        logger.info("   ✅ Área Interna: Ativações culturais")
        logger.info("   ✅ Usa valores diretos do Arduino (distance_raw)")
        logger.info("   ✅ Zonas simplificadas por distância")
        logger.info("   ✅ Tracking preciso e simples") 
        logger.info("   ✅ Menos complexidade, mais eficácia")
        logger.info("   ✅ Envio otimizado a cada 30 segundos")
        logger.info("   ✅ Auto-detecção de porta serial")
        logger.info("   ✅ Display limpo e informativo")
        logger.info("🏢 CONFIGURAÇÃO DUAL GRAVATA:")
        logger.info("   • Radar Externa: Passagem (0-2m) + Interesse (2-5m)")
        logger.info("   • Radar Interna: Ativações (5-10m)")
        logger.info("   • Planilha unificada com zona específica")
        logger.info("   • Monitoramento simultâneo")
        logger.info("=" * 60)
        
        # Mostra status dos radares ativos
        for area, radar in radares_ativos.items():
            config = RADAR_CONFIGS[area]
            logger.info(f"{config['color']} {area}: {config['description']} - Porta {config['port']}")
        
        # Loop principal para múltiplos radares
        while True:
            time.sleep(10)
            
            for area, radar in radares_ativos.items():
                status = radar.get_status()
                config = RADAR_CONFIGS[area]
                
                if status['running'] and status['connected']:
                    logger.debug(f"{config['color']} {area} funcionando: {status['total_detected']} total detectadas")
                else:
                    logger.warning(f"{config['color']} {area} com problemas - tentando reconectar...")
    
    except KeyboardInterrupt:
        logger.info("🛑 Encerrando Sistema Gravata Dual por solicitação do usuário...")
    
    except Exception as e:
        logger.error(f"❌ Erro inesperado: {e}")
    
    finally:
        # Para todos os radares
        for area, radar in radares_ativos.items():
            radar.stop()
            logger.info(f"✅ Radar {area} encerrado!")
        logger.info("✅ Sistema Gravata Dual encerrado!")

if __name__ == "__main__":
    main() 
