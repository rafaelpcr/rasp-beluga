import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
import logging
import os
import traceback
import time
import uuid
import serial
import threading
import json
from dotenv import load_dotenv
import serial.tools.list_ports

# Configuração básica de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('dual_radar_esp32.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('dual_radar_esp32_app')

# Configurando o nível de log para outros módulos
logging.getLogger('urllib3').setLevel(logging.WARNING)
logging.getLogger('gspread').setLevel(logging.WARNING)

load_dotenv()

# Configurações dos radares com suas planilhas específicas
RADAR_CONFIGS = [
    {
        'id': 'RADAR_1',
        'name': 'Contador Entrada Estande (ESP32)',
        'port': '/dev/ttyACM0',  # Será detectado automaticamente
        'baudrate': 115200,
        'spreadsheet_id': '1zVVyL6D9XSrzFvtDxaGJ-3CdniD-gG3Q-bUUXyqr3D4',
        'spreadsheet_name': 'contador_entrada_estande',
        'color': '🔴',
        'description': 'Conta pessoas entrando no estande via ESP32'
    },
    {
        'id': 'RADAR_2', 
        'name': 'Contador Interno Estande (ESP32)',
        'port': '/dev/ttyACM1',  # Será detectado automaticamente
        'baudrate': 115200,
        'spreadsheet_id': '1ACu8Qmicxv7Av-1nAK_dIDbcD_RJBizk2iXspixK2Gg',
        'spreadsheet_name': 'contador_interno_estande',
        'color': '🔵',
        'description': 'Conta pessoas no interior do estande via ESP32'
    }
]

class GoogleSheetsCounterManager:
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
            logger.info(f"✅ Planilha conectada para {radar_id}: {self.spreadsheet.title}")
        except Exception as e:
            logger.error(f"❌ Erro ao conectar à planilha {spreadsheet_id} para {radar_id}: {e}")
            raise
            
        try:
            self.worksheet = self.spreadsheet.get_worksheet(0)
            logger.info(f"✅ Worksheet selecionada: {self.worksheet.title}")
        except Exception as e:
            logger.error(f"❌ Erro ao selecionar worksheet para {radar_id}: {e}")
            raise
        
        self._setup_esp32_headers()

    def _setup_esp32_headers(self):
        """Configura cabeçalhos para dados do ESP32"""
        try:
            headers = self.worksheet.row_values(1)
            expected_headers = [
                'timestamp', 'session_id', 'current_count', 'total_entries', 
                'total_exits', 'max_simultaneous', 'zona_interesse_count',
                'zona_passagem_count', 'session_duration', 'radar_id', 'event_type'
            ]
            
            if not headers or len(headers) < 8:
                logger.info(f"🔧 Configurando cabeçalhos ESP32 para {self.radar_id}")
                self.worksheet.clear()
                self.worksheet.append_row(expected_headers)
            else:
                logger.info(f"✅ Cabeçalhos verificados para {self.radar_id}")
                    
        except Exception as e:
            logger.warning(f"⚠️ Erro ao configurar cabeçalhos para {self.radar_id}: {e}")

    def insert_esp32_data(self, data):
        try:
            row = [
                data.get('timestamp'),
                data.get('session_id'),
                data.get('current_count'),
                data.get('total_entries'),
                data.get('total_exits'),
                data.get('max_simultaneous'),
                data.get('zona_interesse_count'),
                data.get('zona_passagem_count'),
                data.get('session_duration'),
                data.get('radar_id', self.radar_id),
                data.get('event_type', 'UPDATE')
            ]
            
            self.worksheet.append_row(row)
            logger.debug(f'✅ Dados ESP32 do {self.radar_id} enviados para Google Sheets!')
            return True
        except Exception as e:
            logger.error(f'❌ Erro ao enviar dados ESP32 do {self.radar_id}: {str(e)}')
            return False

class ESP32RadarManager:
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
        self.session_id = str(uuid.uuid4())[:8]
        
        # Controle de output
        self.last_output_time = time.time()
        self.OUTPUT_INTERVAL = 10  # 10 segundos entre outputs
        
        # Estatísticas locais
        self.last_data = {}

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
        """Inicia o ESP32 radar em uma thread separada"""
        self.gsheets_manager = gsheets_manager
        
        if not self.connect():
            return False
        
        self.is_running = True
        self.receive_thread = threading.Thread(target=self.receive_data_loop, daemon=True)
        self.receive_thread.start()
        
        logger.info(f"{self.color} {self.radar_name}: 🚀 Iniciado com sucesso!")
        return True

    def stop(self):
        """Para o ESP32 radar"""
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
        """Loop principal de recebimento de dados JSON do ESP32"""
        buffer = ""
        
        logger.info(f"{self.color} {self.radar_name}: 🔄 Loop de dados ESP32 iniciado...")
        
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
                            if line:
                                self.process_esp32_data(line)
                
                # Output periódico
                if time.time() - self.last_output_time > self.OUTPUT_INTERVAL:
                    self.output_statistics()
                    self.last_output_time = time.time()
                
                time.sleep(0.1)
                
            except Exception as e:
                logger.error(f"{self.color} {self.radar_name}: ❌ Erro no loop: {str(e)}")
                time.sleep(1)

    def process_esp32_data(self, raw_data):
        """Processa dados JSON do ESP32"""
        try:
            # Tenta parsear JSON
            if raw_data.startswith('{') and raw_data.endswith('}'):
                json_data = json.loads(raw_data)
                self.handle_json_data(json_data)
            elif '=== ESTATÍSTICAS DE CONTAGEM ===' in raw_data:
                # Ignorar cabeçalhos
                pass
            else:
                # Procurar por dados no formato texto também
                self.handle_text_data(raw_data)
                
        except json.JSONDecodeError:
            # Se não for JSON válido, tentar processar como texto
            self.handle_text_data(raw_data)
        except Exception as e:
            logger.debug(f"{self.color} {self.radar_name}: Erro ao processar dados: {str(e)}")

    def handle_json_data(self, json_data):
        """Processa dados JSON do ESP32"""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        # Extrair dados principais
        current_count = json_data.get('current_count', 0)
        total_entries = json_data.get('total_entries', 0)
        total_exits = json_data.get('total_exits', 0)
        max_simultaneous = json_data.get('max_simultaneous', 0)
        session_duration = json_data.get('session_duration', 0)
        zona_interesse_count = json_data.get('zona_interesse_count', 0)
        zona_passagem_count = json_data.get('zona_passagem_count', 0)
        
        # Atualizar estatísticas locais
        self.last_data = {
            'timestamp': timestamp,
            'session_id': self.session_id,
            'current_count': current_count,
            'total_entries': total_entries,
            'total_exits': total_exits,
            'max_simultaneous': max_simultaneous,
            'zona_interesse_count': zona_interesse_count,
            'zona_passagem_count': zona_passagem_count,
            'session_duration': session_duration,
            'radar_id': self.radar_id,
            'event_type': 'JSON_UPDATE'
        }
        
        # Enviar para planilha
        if self.gsheets_manager:
            success = self.gsheets_manager.insert_esp32_data(self.last_data)
            if success:
                logger.debug(f"{self.color} {self.radar_name}: 📊 Dados JSON enviados para planilha")

    def handle_text_data(self, text_data):
        """Processa dados em texto do ESP32"""
        if 'current_count:' in text_data or 'total_entries:' in text_data:
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            # Enviar dados básicos
            basic_data = {
                'timestamp': timestamp,
                'session_id': self.session_id,
                'current_count': 0,
                'total_entries': 0,
                'total_exits': 0,
                'max_simultaneous': 0,
                'zona_interesse_count': 0,
                'zona_passagem_count': 0,
                'session_duration': 0,
                'radar_id': self.radar_id,
                'event_type': 'TEXT_UPDATE'
            }
            
            if self.gsheets_manager:
                self.gsheets_manager.insert_esp32_data(basic_data)

    def output_statistics(self):
        """Exibir estatísticas atuais do ESP32"""
        if not self.last_data:
            current_count = 0
            zona_interesse = 0
            zona_passagem = 0
            total_entries = 0
            total_exits = 0
            max_simultaneous = 0
            session_duration = 0
        else:
            current_count = self.last_data.get('current_count', 0)
            zona_interesse = self.last_data.get('zona_interesse_count', 0)
            zona_passagem = self.last_data.get('zona_passagem_count', 0)
            total_entries = self.last_data.get('total_entries', 0)
            total_exits = self.last_data.get('total_exits', 0)
            max_simultaneous = self.last_data.get('max_simultaneous', 0)
            session_duration = self.last_data.get('session_duration', 0)
        
        if self.radar_id == 'RADAR_1':
            zone1_name = "ENTRADA"
            zone2_name = "PASSAGEM"
        else:
            zone1_name = "INTERESSE"
            zone2_name = "CIRCULACAO"
        
        output = [
            f"\n{self.color} ═══ {self.radar_name.upper()} ═══",
            f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"📊 Sessão: {self.session_id}",
            "-" * 50,
            f"👤 Pessoas Ativas: {current_count}",
            f"🎯 Zona {zone1_name}: {zona_interesse} pessoas",
            f"🚶 Zona {zone2_name}: {zona_passagem} pessoas", 
            f"📈 Máximo Simultâneo: {max_simultaneous}",
            f"🎯 Total Entradas: {total_entries}",
            f"🚶 Total Saídas: {total_exits}",
            f"⏱️ Duração da Sessão: {session_duration}s",
            "═" * 50
        ]
        
        logger.info("\n".join(output))

class ESP32DualRadarSystem:
    def __init__(self):
        self.radars = []
        self.gsheets_managers = {}
        
    def detect_available_ports(self):
        """Detecta portas seriais disponíveis e atualiza configurações"""
        logger.info("🔍 Detectando portas seriais disponíveis para ESP32...")
        
        ports = list(serial.tools.list_ports.comports())
        radar_ports = []
        
        for port in ports:
            desc_lower = port.description.lower()
            if any(term in desc_lower for term in 
                   ['usb', 'serial', 'uart', 'cp210', 'ch340', 'ft232', 'arduino', 'esp32', 'acm', 'jtag']):
                radar_ports.append(port.device)
                logger.info(f"   📡 Porta detectada: {port.device} ({port.description})")
        
        if len(radar_ports) >= 2:
            for i, config in enumerate(RADAR_CONFIGS[:2]):
                if i < len(radar_ports):
                    config['port'] = radar_ports[i]
                    logger.info(f"   ✅ {config['name']} configurado para {radar_ports[i]}")
            return True
        else:
            logger.error(f"❌ Apenas {len(radar_ports)} portas encontradas. Necessárias 2 para dual radar.")
            return False

    def initialize(self):
        """Inicializa o sistema dual ESP32 radar"""
        logger.info("🚀 Inicializando Sistema Dual ESP32 Contador de Pessoas...")
        
        if not self.detect_available_ports():
            return False
        
        script_dir = os.path.dirname(os.path.abspath(__file__))
        credentials_file = os.path.join(script_dir, 'serial_radar', 'credenciais.json')
        
        for config in RADAR_CONFIGS:
            try:
                gsheets_manager = GoogleSheetsCounterManager(
                    credentials_file, 
                    config['spreadsheet_id'],
                    config['id']
                )
                self.gsheets_managers[config['id']] = gsheets_manager
                logger.info(f"✅ Google Sheets configurado para {config['name']}")
            except Exception as e:
                logger.error(f"❌ Erro ao configurar Sheets para {config['name']}: {e}")
                return False
        
        for config in RADAR_CONFIGS:
            radar = ESP32RadarManager(config)
            self.radars.append(radar)
        
        return True

    def start(self):
        """Inicia todos os ESP32s"""
        logger.info("🚀 Iniciando contagem de pessoas via ESP32...")
        
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
        
        logger.info("🎯 Sistema ESP32 de contagem de pessoas ativo!")
        return True

    def stop(self):
        """Para todos os ESP32s"""
        logger.info("🛑 Parando contagem de pessoas ESP32...")
        
        for radar in self.radars:
            radar.stop()
        
        logger.info("✅ Sistema ESP32 encerrado!")

    def get_status(self):
        """Retorna status do sistema"""
        status = {
            'total_radars': len(self.radars),
            'running_radars': sum(1 for r in self.radars if r.is_running),
            'radars': []
        }
        
        for radar in self.radars:
            current_count = radar.last_data.get('current_count', 0) if radar.last_data else 0
            total_entries = radar.last_data.get('total_entries', 0) if radar.last_data else 0
            
            radar_status = {
                'id': radar.radar_id,
                'name': radar.radar_name,
                'port': radar.port,
                'running': radar.is_running,
                'connected': radar.serial_connection and radar.serial_connection.is_open if radar.serial_connection else False,
                'description': radar.description,
                'current_count': current_count,
                'total_entries': total_entries
            }
            status['radars'].append(radar_status)
        
        return status

def main():
    """Função principal"""
    esp32_system = ESP32DualRadarSystem()
    
    try:
        if not esp32_system.initialize():
            logger.error("❌ Falha na inicialização do sistema ESP32")
            return
        
        if not esp32_system.start():
            logger.error("❌ Falha ao iniciar os ESP32s") 
            return
        
        status = esp32_system.get_status()
        logger.info("=" * 70)
        logger.info("👥 SISTEMA CONTADOR DE PESSOAS ESP32 - ESTANDE ATIVO")
        logger.info("=" * 70)
        for radar_status in status['radars']:
            status_icon = "🟢" if radar_status['running'] else "🔴"
            logger.info(f"{status_icon} {radar_status['name']}: {radar_status['port']}")
            logger.info(f"    📋 {radar_status['description']}")
        logger.info("⚡ Pressione Ctrl+C para encerrar")
        logger.info("=" * 70)
        
        while True:
            time.sleep(5)
            
            if int(time.time()) % 30 == 0:
                current_status = esp32_system.get_status()
                total_people = sum(r['current_count'] for r in current_status['radars'])
                total_entries = sum(r['total_entries'] for r in current_status['radars'])
                
                if current_status['running_radars'] != current_status['total_radars']:
                    logger.warning(f"⚠️ Apenas {current_status['running_radars']}/{current_status['total_radars']} ESP32s ativos")
                else:
                    logger.info(f"📊 RESUMO ESP32: {total_people} pessoas ativas | {total_entries} entradas totais")
    
    except KeyboardInterrupt:
        logger.info("🛑 Encerrando por solicitação do usuário...")
    
    except Exception as e:
        logger.error(f"❌ Erro inesperado: {str(e)}")
        logger.error(traceback.format_exc())
    
    finally:
        esp32_system.stop()

if __name__ == "__main__":
    main() 
