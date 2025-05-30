import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
import logging
import os
import traceback
import time
import numpy as np
import uuid
import serial
import threading
import re
import math
from dotenv import load_dotenv
import serial.tools.list_ports

# Configuração básica de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('dual_radar_serial.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('dual_radar_app')

# Configurando o nível de log para outros módulos
logging.getLogger('urllib3').setLevel(logging.WARNING)
logging.getLogger('gspread').setLevel(logging.WARNING)

load_dotenv()

# Configurações dos radares com suas planilhas específicas
RADAR_CONFIGS = [
    {
        'id': 'RADAR_1',
        'name': 'Radar Entrada Estande',
        'port': '/dev/ttyACM0',  # Será detectado automaticamente
        'baudrate': 115200,
        'spreadsheet_id': '1zVVyL6D9XSrzFvtDxaGJ-3CdniD-gG3Q-bUUXyqr3D4',  # Planilha entrada estande
        'spreadsheet_name': 'dados_radar_entrada_estande',
        'color': '🔴',
        'description': 'Monitora a entrada do estande'
    },
    {
        'id': 'RADAR_2', 
        'name': 'Radar Interno Estande',
        'port': '/dev/ttyACM1',  # Será detectado automaticamente
        'baudrate': 115200,
        'spreadsheet_id': '1ACu8Qmicxv7Av-1nAK_dIDbcD_RJBizk2iXspixK2Gg',  # Planilha interno estande
        'spreadsheet_name': 'dados_radar_interno_estande',
        'color': '🔵',
        'description': 'Monitora o interior do estande'
    }
]

RANGE_STEP = 2.5

class GoogleSheetsManager:
    def __init__(self, creds_path, spreadsheet_id, radar_id, worksheet_name='Sheet1'):
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
            # Abre a planilha pelo ID específico
            self.spreadsheet = self.gc.open_by_key(spreadsheet_id)
            logger.info(f"✅ Planilha conectada para {radar_id}: {self.spreadsheet.title}")
        except Exception as e:
            logger.error(f"❌ Erro ao conectar à planilha {spreadsheet_id} para {radar_id}: {e}")
            raise
            
        # Seleciona a primeira worksheet disponível
        try:
            self.worksheet = self.spreadsheet.get_worksheet(0)  # Primeira aba
            logger.info(f"✅ Worksheet selecionada: {self.worksheet.title}")
        except Exception as e:
            logger.error(f"❌ Erro ao selecionar worksheet para {radar_id}: {e}")
            raise
        
        # Verifica se os cabeçalhos estão corretos
        self._verify_headers()

    def _verify_headers(self):
        """Verifica se os cabeçalhos da planilha estão corretos"""
        try:
            headers = self.worksheet.row_values(1)
            expected_headers = [
                'session_id', 'timestamp', 'x_point', 'y_point', 
                'move_speed', 'heart_rate', 'breath_rate', 'distance',
                'section_id', 'product_id', 'satisfaction_score', 
                'satisfaction_class', 'is_engaged'
            ]
            
            if headers and len(headers) >= len(expected_headers):
                logger.info(f"✅ Cabeçalhos verificados para {self.radar_id}")
                # Vamos adicionar a coluna radar_id se não existir
                if 'radar_id' not in headers:
                    logger.info(f"🔧 Adicionando coluna radar_id para {self.radar_id}")
                    # Adiciona o cabeçalho radar_id na próxima coluna disponível
                    next_col = len(headers) + 1
                    self.worksheet.update_cell(1, next_col, 'radar_id')
            else:
                logger.warning(f"⚠️ Cabeçalhos não encontrados ou incompletos para {self.radar_id}")
                
        except Exception as e:
            logger.warning(f"⚠️ Erro ao verificar cabeçalhos para {self.radar_id}: {e}")

    def insert_radar_data(self, data):
        try:
            # Prepara os dados conforme a ordem das colunas
            row = [
                data.get('session_id'),
                data.get('timestamp'),
                data.get('x_point'),
                data.get('y_point'),
                data.get('move_speed'),
                data.get('heart_rate'),
                data.get('breath_rate'),
                data.get('distance'),
                data.get('section_id'),
                data.get('product_id'),
                data.get('satisfaction_score'),
                data.get('satisfaction_class'),
                data.get('is_engaged'),
                data.get('radar_id', self.radar_id)  # Adiciona ID do radar
            ]
            
            self.worksheet.append_row(row)
            logger.debug(f'✅ Dados do {self.radar_id} enviados para Google Sheets!')
            return True
        except Exception as e:
            logger.error(f'❌ Erro ao enviar dados do {self.radar_id} para Google Sheets: {str(e)}')
            logger.error(traceback.format_exc())
            return False

def parse_serial_data(raw_data):
    """Função para parsear dados seriais (mesma do código original)"""
    try:
        x_pattern = r'x_point\s*:\s*([-+]?\d*\.?\d+)'
        y_pattern = r'y_point\s*:\s*([-+]?\d*\.?\d+)'
        dop_pattern = r'dop_index\s*:\s*([-+]?\d+)'
        cluster_pattern = r'cluster_index\s*:\s*(\d+)'
        speed_pattern = r'move_speed\s*:\s*([-+]?\d*\.?\d+)\s*cm/s'
        total_phase_pattern = r'total_phase\s*:\s*([-+]?\d*\.?\d+)'
        breath_phase_pattern = r'breath_phase\s*:\s*([-+]?\d*\.?\d+)'
        heart_phase_pattern = r'heart_phase\s*:\s*([-+]?\d*\.?\d+)'
        breath_rate_pattern = r'breath_rate\s*:\s*([-+]?\d*\.?\d+)'
        heart_rate_pattern = r'heart_rate\s*:\s*([-+]?\d*\.?\d+)'
        distance_pattern = r'distance\s*:\s*([-+]?\d*\.?\d+)'

        if '-----Human Detected-----' not in raw_data:
            return None
        if 'Target 1:' not in raw_data:
            return None

        x_match = re.search(x_pattern, raw_data, re.IGNORECASE)
        y_match = re.search(y_pattern, raw_data, re.IGNORECASE)
        dop_match = re.search(dop_pattern, raw_data, re.IGNORECASE)
        cluster_match = re.search(cluster_pattern, raw_data, re.IGNORECASE)
        speed_match = re.search(speed_pattern, raw_data, re.IGNORECASE)
        total_phase_match = re.search(total_phase_pattern, raw_data, re.IGNORECASE)
        breath_phase_match = re.search(breath_phase_pattern, raw_data, re.IGNORECASE)
        heart_phase_match = re.search(heart_phase_pattern, raw_data, re.IGNORECASE)
        breath_rate_match = re.search(breath_rate_pattern, raw_data, re.IGNORECASE)
        heart_rate_match = re.search(heart_rate_pattern, raw_data, re.IGNORECASE)
        distance_match = re.search(distance_pattern, raw_data, re.IGNORECASE)

        if x_match and y_match:
            data = {
                'x_point': float(x_match.group(1)),
                'y_point': float(y_match.group(1)),
                'dop_index': int(dop_match.group(1)) if dop_match else 0,
                'cluster_index': int(cluster_match.group(1)) if cluster_match else 0,
                'move_speed': float(speed_match.group(1))/100 if speed_match else 0.0,
                'total_phase': float(total_phase_match.group(1)) if total_phase_match else 0.0,
                'breath_phase': float(breath_phase_match.group(1)) if breath_phase_match else 0.0,
                'heart_phase': float(heart_phase_match.group(1)) if heart_phase_match else 0.0,
                'breath_rate': float(breath_rate_match.group(1)) if breath_rate_match else None,
                'heart_rate': float(heart_rate_match.group(1)) if heart_rate_match else None,
                'distance': float(distance_match.group(1)) if distance_match else None
            }

            if data['distance'] is None:
                data['distance'] = math.sqrt(data['x_point']**2 + data['y_point']**2)
            if data['heart_rate'] is None:
                data['heart_rate'] = 75.0
            if data['breath_rate'] is None:
                data['breath_rate'] = 15.0
            
            return data
        else:
            return None
    except Exception as e:
        logger.error(f"❌ Erro ao analisar dados seriais: {str(e)}")
        logger.error(traceback.format_exc())
        return None

class ShelfManager:
    def __init__(self, radar_id):
        self.radar_id = radar_id
        self.SECTION_WIDTH = 0.5
        self.SECTION_HEIGHT = 0.3
        self.MAX_SECTIONS_X = 3
        self.MAX_SECTIONS_Y = 1
        
        # Seções específicas por radar baseadas na localização real
        if radar_id == 'RADAR_1':  # Entrada do estande
            self.sections = [
                {
                    'section_id': 1,
                    'section_name': 'Entrada Principal',
                    'product_id': 'ENTRADA_001',
                    'x_start': -0.5, 'y_start': 0.0,
                    'x_end': 0.5, 'y_end': 2.0
                },
                {
                    'section_id': 2,
                    'section_name': 'Corredor Entrada',
                    'product_id': 'ENTRADA_002',
                    'x_start': 0.5, 'y_start': 0.0,
                    'x_end': 1.5, 'y_end': 2.0
                }
            ]
        else:  # RADAR_2 - Interior do estande
            self.sections = [
                {
                    'section_id': 3,
                    'section_name': 'Área Central',
                    'product_id': 'INTERNO_001',
                    'x_start': -1.0, 'y_start': 0.0,
                    'x_end': 0.0, 'y_end': 2.0
                },
                {
                    'section_id': 4,
                    'section_name': 'Área Produtos',
                    'product_id': 'INTERNO_002',
                    'x_start': 0.0, 'y_start': 0.0,
                    'x_end': 1.0, 'y_end': 2.0
                }
            ]

    def get_section_at_position(self, x, y):
        for section in self.sections:
            if (section['x_start'] <= x <= section['x_end'] and 
                section['y_start'] <= y <= section['y_end']):
                return section
        return None

class AnalyticsManager:
    def __init__(self):
        self.MOVEMENT_THRESHOLD = 20.0
        self.DISTANCE_THRESHOLD = 2.0
        self.HEART_RATE_NORMAL = (60, 100)
        self.BREATH_RATE_NORMAL = (12, 20)

    def calculate_satisfaction_score(self, move_speed, heart_rate, breath_rate, distance):
        try:
            score = 0.0
            
            if move_speed is not None:
                if move_speed <= self.MOVEMENT_THRESHOLD:
                    score += 30
                else:
                    score += max(0, 30 * (1 - move_speed/100))
            
            if distance is not None:
                if distance <= self.DISTANCE_THRESHOLD:
                    score += 20
                else:
                    score += max(0, 20 * (1 - distance/5))
            
            if heart_rate is not None:
                if self.HEART_RATE_NORMAL[0] <= heart_rate <= self.HEART_RATE_NORMAL[1]:
                    score += 25
                else:
                    deviation = min(
                        abs(heart_rate - self.HEART_RATE_NORMAL[0]),
                        abs(heart_rate - self.HEART_RATE_NORMAL[1])
                    )
                    score += max(0, 25 * (1 - deviation/50))
            
            if breath_rate is not None:
                if self.BREATH_RATE_NORMAL[0] <= breath_rate <= self.BREATH_RATE_NORMAL[1]:
                    score += 25
                else:
                    deviation = min(
                        abs(breath_rate - self.BREATH_RATE_NORMAL[0]),
                        abs(breath_rate - self.BREATH_RATE_NORMAL[1])
                    )
                    score += max(0, 25 * (1 - deviation/20))

            if score >= 85:
                classification = "MUITO_POSITIVA"
            elif score >= 70:
                classification = "POSITIVA"
            elif score >= 50:
                classification = "NEUTRA"
            elif score >= 30:
                classification = "NEGATIVA"
            else:
                classification = "MUITO_NEGATIVA"
                
            return (score, classification)
        except Exception as e:
            logger.error(f"Erro ao calcular satisfação: {str(e)}")
            return (50.0, "NEUTRA")

class RadarManager:
    def __init__(self, radar_config):
        self.config = radar_config
        self.radar_id = radar_config['id']
        self.radar_name = radar_config['name']
        self.port = radar_config['port']
        self.baudrate = radar_config['baudrate']
        self.color = radar_config['color']
        self.description = radar_config['description']
        
        self.serial_connection = None
        self.is_running = False
        self.receive_thread = None
        self.gsheets_manager = None
        self.analytics_manager = AnalyticsManager()
        self.shelf_manager = ShelfManager(self.radar_id)
        
        # Controle de sessão
        self.current_session_id = None
        self.last_activity_time = None
        self.SESSION_TIMEOUT = 60
        
        # Buffer para engajamento
        self.engagement_buffer = []
        self.ENGAGEMENT_WINDOW = 1
        self.ENGAGEMENT_DISTANCE = 1.5  # Ajustado para estandes
        self.ENGAGEMENT_SPEED = 15.0    # Ajustado para movimento em estandes

    def _generate_session_id(self):
        return f"{self.radar_id}_{str(uuid.uuid4())[:8]}"

    def find_serial_port(self):
        """Detecta automaticamente a porta serial se a configurada não existir"""
        ports = list(serial.tools.list_ports.comports())
        if not ports:
            logger.error(f"{self.color} {self.radar_name}: Nenhuma porta serial encontrada!")
            return None
        
        # Primeiro tenta a porta configurada
        for port in ports:
            if port.device == self.port:
                return self.port
        
        # Se não encontrou, procura por dispositivos apropriados
        for port in ports:
            desc_lower = port.description.lower()
            if any(term in desc_lower for term in
                  ['usb', 'serial', 'uart', 'cp210', 'ch340', 'ft232', 'arduino', 'esp32', 'jtag']):
                logger.warning(f"{self.color} {self.radar_name}: Porta {self.port} não encontrada, usando {port.device}")
                return port.device
        
        logger.error(f"{self.color} {self.radar_name}: Nenhuma porta adequada encontrada!")
        return None

    def connect(self):
        """Conecta à porta serial"""
        # Verifica se a porta existe, senão tenta detectar automaticamente
        if not os.path.exists(self.port):
            detected_port = self.find_serial_port()
            if detected_port:
                self.port = detected_port
            else:
                return False
        
        try:
            logger.info(f"{self.color} {self.radar_name}: Conectando à porta {self.port} (baudrate: {self.baudrate})...")
            
            self.serial_connection = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=1,
                write_timeout=1,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE
            )
            time.sleep(2)
            logger.info(f"{self.color} {self.radar_name}: ✅ Conexão estabelecida!")
            return True
        except Exception as e:
            logger.error(f"{self.color} {self.radar_name}: ❌ Erro ao conectar: {str(e)}")
            return False

    def start(self, gsheets_manager):
        """Inicia o radar em uma thread separada"""
        self.gsheets_manager = gsheets_manager
        
        if not self.connect():
            return False
        
        self.is_running = True
        self.receive_thread = threading.Thread(target=self.receive_data_loop, daemon=True)
        self.receive_thread.start()
        
        logger.info(f"{self.color} {self.radar_name}: 🚀 Iniciado com sucesso!")
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
        
        logger.info(f"{self.color} {self.radar_name}: 🛑 Parado!")

    def receive_data_loop(self):
        """Loop principal de recebimento de dados"""
        buffer = ""
        message_mode = False
        message_buffer = ""
        
        logger.info(f"{self.color} {self.radar_name}: 🔄 Loop de dados iniciado...")
        
        while self.is_running:
            try:
                if not self.serial_connection.is_open:
                    logger.warning(f"{self.color} {self.radar_name}: ⚠️ Reconectando...")
                    self.connect()
                    time.sleep(1)
                    continue
                
                in_waiting = self.serial_connection.in_waiting or 0
                data = self.serial_connection.read(in_waiting or 1)
                
                if data:
                    text = data.decode('utf-8', errors='ignore')
                    buffer += text
                    
                    if '\n' in buffer:
                        lines = buffer.split('\n')
                        buffer = lines[-1]
                        
                        for line in lines[:-1]:
                            line = line.strip()
                            
                            if '-----Human Detected-----' in line:
                                if not message_mode:
                                    message_mode = True
                                    message_buffer = line + '\n'
                            elif message_mode:
                                message_buffer += line + '\n'
                                if 'move_speed:' in line:
                                    self.process_radar_data(message_buffer)
                                    message_mode = False
                                    message_buffer = ""
                
                time.sleep(0.01)
                
            except Exception as e:
                logger.error(f"{self.color} {self.radar_name}: ❌ Erro no loop: {str(e)}")
                time.sleep(1)

    def process_radar_data(self, raw_data):
        """Processa os dados do radar"""
        try:
            data = parse_serial_data(raw_data)
            if not data:
                return

            # Gera ou atualiza sessão
            if not self.current_session_id:
                self.current_session_id = self._generate_session_id()
            
            # Calcula dados processados
            x = data.get('x_point', 0)
            y = data.get('y_point', 0)
            move_speed = abs(data.get('dop_index', 0) * RANGE_STEP)
            distance = data.get('distance', math.sqrt(x**2 + y**2))
            
            converted_data = {
                'session_id': self.current_session_id,
                'x_point': x,
                'y_point': y,
                'move_speed': move_speed,
                'distance': distance,
                'heart_rate': data.get('heart_rate', 75.0),
                'breath_rate': data.get('breath_rate', 15.0),
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'radar_id': self.radar_id
            }
            
            # Determina seção
            section = self.shelf_manager.get_section_at_position(x, y)
            if section:
                converted_data['section_id'] = section['section_id']
                converted_data['product_id'] = section['product_id']
            else:
                converted_data['section_id'] = None
                converted_data['product_id'] = None
            
            # Calcula engajamento
            converted_data['is_engaged'] = self._check_engagement(distance, move_speed)
            
            # Calcula satisfação
            satisfaction_score, satisfaction_class = self.analytics_manager.calculate_satisfaction_score(
                move_speed, converted_data['heart_rate'], converted_data['breath_rate'], distance
            )
            converted_data['satisfaction_score'] = satisfaction_score
            converted_data['satisfaction_class'] = satisfaction_class

            # Log formatado
            self._log_data(converted_data, section)
            
            # Envia para Google Sheets
            if self.gsheets_manager:
                success = self.gsheets_manager.insert_radar_data(converted_data)
                if not success:
                    logger.error(f"{self.color} {self.radar_name}: ❌ Falha ao enviar para Sheets")
            
        except Exception as e:
            logger.error(f"{self.color} {self.radar_name}: ❌ Erro ao processar dados: {str(e)}")

    def _check_engagement(self, distance, move_speed):
        """Verifica engajamento baseado na distância e velocidade"""
        return distance <= self.ENGAGEMENT_DISTANCE and move_speed <= self.ENGAGEMENT_SPEED

    def _log_data(self, data, section):
        """Log formatado dos dados"""
        section_name = section['section_name'] if section else 'Fora da área'
        
        output = [
            f"\n{self.color} ═══ {self.radar_name.upper()} ═══",
            f"⏰ {data['timestamp']}",
            f"📍 LOCAL: {section_name}",
            f"📊 POS: X:{data['x_point']:6.2f} Y:{data['y_point']:6.2f} D:{data['distance']:6.2f}",
            f"🏃 VEL: {data['move_speed']:6.2f} cm/s",
            f"❤️  HR: {data['heart_rate']:6.1f} bpm | BR: {data['breath_rate']:6.1f} rpm",
            f"🎯 ENG: {'✅' if data['is_engaged'] else '❌'} | SCORE: {data['satisfaction_score']:6.1f}",
            f"══════════════════════════════════════════"
        ]
        
        logger.info("\n".join(output))

class EstandeRadarSystem:
    def __init__(self):
        self.radars = []
        self.gsheets_managers = {}
        
    def detect_available_ports(self):
        """Detecta portas seriais disponíveis e atualiza configurações"""
        logger.info("🔍 Detectando portas seriais disponíveis...")
        
        ports = list(serial.tools.list_ports.comports())
        radar_ports = []
        
        for port in ports:
            desc_lower = port.description.lower()
            if any(term in desc_lower for term in 
                   ['usb', 'serial', 'uart', 'cp210', 'ch340', 'ft232', 'arduino', 'esp32', 'acm', 'jtag']):
                radar_ports.append(port.device)
                logger.info(f"   📡 Porta detectada: {port.device} ({port.description})")
        
        if len(radar_ports) >= 2:
            # Atualiza as configurações com as portas encontradas
            for i, config in enumerate(RADAR_CONFIGS[:2]):
                if i < len(radar_ports):
                    config['port'] = radar_ports[i]
                    logger.info(f"   ✅ {config['name']} configurado para {radar_ports[i]}")
            return True
        else:
            logger.error(f"❌ Apenas {len(radar_ports)} portas encontradas. Necessárias 2 para dual radar.")
            return False

    def initialize(self):
        """Inicializa o sistema dual radar"""
        logger.info("🚀 Inicializando Sistema Dual Radar para Estande...")
        
        # Detecta portas disponíveis
        if not self.detect_available_ports():
            return False
        
        # Inicializa Google Sheets para cada radar usando IDs específicos
        script_dir = os.path.dirname(os.path.abspath(__file__))
        credentials_file = os.path.join(script_dir, 'serial_radar', 'credenciais.json')
        
        for config in RADAR_CONFIGS:
            try:
                gsheets_manager = GoogleSheetsManager(
                    credentials_file, 
                    config['spreadsheet_id'],  # Usando ID em vez de nome
                    config['id']
                )
                self.gsheets_managers[config['id']] = gsheets_manager
                logger.info(f"✅ Google Sheets configurado para {config['name']}")
            except Exception as e:
                logger.error(f"❌ Erro ao configurar Sheets para {config['name']}: {e}")
                return False
        
        # Inicializa radares
        for config in RADAR_CONFIGS:
            radar = RadarManager(config)
            self.radars.append(radar)
        
        return True

    def start(self):
        """Inicia todos os radares"""
        logger.info("🚀 Iniciando monitoramento do estande...")
        
        for radar in self.radars:
            gsheets_manager = self.gsheets_managers.get(radar.radar_id)
            if gsheets_manager:
                success = radar.start(gsheets_manager)
                if not success:
                    logger.error(f"❌ Falha ao iniciar {radar.radar_name}")
                    return False
            else:
                logger.error(f"❌ Google Sheets não encontrado para {radar.radar_name}")
                return False
        
        logger.info("🎯 Sistema de monitoramento do estande ativo!")
        return True

    def stop(self):
        """Para todos os radares"""
        logger.info("🛑 Parando monitoramento do estande...")
        
        for radar in self.radars:
            radar.stop()
        
        logger.info("✅ Sistema encerrado!")

    def get_status(self):
        """Retorna status do sistema"""
        status = {
            'total_radars': len(self.radars),
            'running_radars': sum(1 for r in self.radars if r.is_running),
            'radars': []
        }
        
        for radar in self.radars:
            radar_status = {
                'id': radar.radar_id,
                'name': radar.radar_name,
                'port': radar.port,
                'running': radar.is_running,
                'connected': radar.serial_connection and radar.serial_connection.is_open if radar.serial_connection else False,
                'description': radar.description
            }
            status['radars'].append(radar_status)
        
        return status

def main():
    """Função principal"""
    estande_system = EstandeRadarSystem()
    
    try:
        # Inicializa o sistema
        if not estande_system.initialize():
            logger.error("❌ Falha na inicialização do sistema")
            return
        
        # Inicia os radares
        if not estande_system.start():
            logger.error("❌ Falha ao iniciar os radares") 
            return
        
        # Exibe status
        status = estande_system.get_status()
        logger.info("=" * 70)
        logger.info("🏢 SISTEMA DE MONITORAMENTO DO ESTANDE ATIVO")
        logger.info("=" * 70)
        for radar_status in status['radars']:
            status_icon = "🟢" if radar_status['running'] else "🔴"
            logger.info(f"{status_icon} {radar_status['name']}: {radar_status['port']}")
            logger.info(f"    📋 {radar_status['description']}")
        logger.info("⚡ Pressione Ctrl+C para encerrar")
        logger.info("=" * 70)
        
        # Mantém o sistema rodando
        while True:
            time.sleep(1)
            
            # Verifica status periodicamente (a cada 30 segundos)
            if int(time.time()) % 30 == 0:
                current_status = estande_system.get_status()
                if current_status['running_radars'] != current_status['total_radars']:
                    logger.warning(f"⚠️ Apenas {current_status['running_radars']}/{current_status['total_radars']} radares ativos")
    
    except KeyboardInterrupt:
        logger.info("🛑 Encerrando por solicitação do usuário...")
    
    except Exception as e:
        logger.error(f"❌ Erro inesperado: {str(e)}")
        logger.error(traceback.format_exc())
    
    finally:
        estande_system.stop()

if __name__ == "__main__":
    main() 
