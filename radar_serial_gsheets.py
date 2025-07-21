#oi
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

# Configuração básica de logging
logging.basicConfig(
    level=logging.INFO,  # Mudando para INFO para reduzir mensagens de debug
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('radar_serial.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('radar_serial_app')

# Configurando o nível de log para outros módulos
logging.getLogger('urllib3').setLevel(logging.WARNING)
logging.getLogger('gspread').setLevel(logging.WARNING)

load_dotenv()

SERIAL_CONFIG = {
    'port': os.getenv('SERIAL_PORT', '/dev/ttyACM0'),
    'baudrate': int(os.getenv('SERIAL_BAUDRATE', 115200))
}
RANGE_STEP = 2.5

class GoogleSheetsManager:
    def __init__(self, creds_path, spreadsheet_name, worksheet_name='Sheet1'):
        SCOPES = [
            'https://www.googleapis.com/auth/spreadsheets',
            'https://www.googleapis.com/auth/drive',
            'https://www.googleapis.com/auth/drive.file'
        ]
        self.creds = Credentials.from_service_account_file(creds_path, scopes=SCOPES)
        self.gc = gspread.authorize(self.creds)
        self.spreadsheet = self.gc.open(spreadsheet_name)
        self.worksheet = self.spreadsheet.worksheet(worksheet_name)

    def insert_radar_data(self, data):
        try:
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
                data.get('is_engaged')
            ]
            self.worksheet.append_row(row)
            logger.info('✅ Dados enviados para o Google Sheets!')
            return True
        except Exception as e:
            logger.error(f'❌ Erro ao enviar dados para o Google Sheets: {str(e)}')
            logger.error(traceback.format_exc())
            return False

def parse_serial_data(raw_data):
    try:
        # Regex ainda mais tolerante: aceita espaços extras, quebras de linha e maiúsculas/minúsculas
        x_pattern = r'x_point\s*:\s*([-+]?\d*\.?\d+)'  # aceita inteiro ou float, sinal opcional
        y_pattern = r'y_point\s*:\s*([-+]?\d*\.?\d+)'
        dop_pattern = r'dop_index\s*:\s*([-+]?\d+)'  # aceita sinal opcional
        cluster_pattern = r'cluster_index\s*:\s*(\d+)'
        speed_pattern = r'move_speed\s*:\s*([-+]?\d*\.?\d+)\s*cm/s'
        total_phase_pattern = r'total_phase\s*:\s*([-+]?\d*\.?\d+)'
        breath_phase_pattern = r'breath_phase\s*:\s*([-+]?\d*\.?\d+)'
        heart_phase_pattern = r'heart_phase\s*:\s*([-+]?\d*\.?\d+)'
        breath_rate_pattern = r'breath_rate\s*:\s*([-+]?\d*\.?\d+)'
        heart_rate_pattern = r'heart_rate\s*:\s*([-+]?\d*\.?\d+)'
        distance_pattern = r'distance\s*:\s*([-+]?\d*\.?\d+)'
        # Usar flags re.IGNORECASE para aceitar maiúsculas/minúsculas
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

def convert_radar_data(raw_data):
    """Converte dados brutos do radar para o formato do banco de dados"""
    try:
        # Verificar se já é um dicionário
        if isinstance(raw_data, dict):
            data = raw_data
        else:
            # Tentar parsear como JSON primeiro
            try:
                data = json.loads(raw_data)
            except:
                # Se não for JSON, tentar parsear como texto da serial
                data = parse_serial_data(raw_data)
                if not data:
                    return None

        # Garantir que todos os campos necessários estão presentes
        result = {
            'x_point': float(data.get('x_point', 0)),
            'y_point': float(data.get('y_point', 0)),
            'move_speed': float(data.get('move_speed', 0)),
            'heart_rate': float(data.get('heart_rate', 75)),
            'breath_rate': float(data.get('breath_rate', 15))
        }

        return result
    except Exception as e:
        logger.error(f"Erro ao converter dados do radar: {str(e)}")
        logger.error(traceback.format_exc())
        return None

class ShelfManager:
    def __init__(self):
        self.SECTION_WIDTH = 0.5  # metros
        self.SECTION_HEIGHT = 0.3  # metros
        self.MAX_SECTIONS_X = 3
        self.MAX_SECTIONS_Y = 1
        self.SCALE_FACTOR = 1  # Não precisa mais de escala
        self.sections = [
            {
                'section_id': 1,
                'section_name': 'Granolas Premium',
                'product_id': '1',
                'x_start': -1.0,
                'y_start': 0.0,
                'x_end': -0.15,
                'y_end': 1.5
            },
            {
                'section_id': 2,
                'section_name': 'Mix de Frutas Secas',
                'product_id': '2',
                'x_start': -0.15,
                'y_start': 0.0,
                'x_end': 0.15,
                'y_end': 1.5
            },
            {
                'section_id': 3,
                'section_name': 'Barras de Cereais',
                'product_id': '3',
                'x_start': 0.15,
                'y_start': 0.0,
                'x_end': 1.0,
                'y_end': 1.5
            }
        ]

    def get_section_at_position(self, x, y, db_manager=None):
        logger.debug(f"Coordenadas recebidas - X: {x:.2f}m, Y: {y:.2f}m")
        if x < -1.0 or x > 1.0 or y < 0 or y > 1.5:
            logger.debug(f"⚠️ Coordenadas fora dos limites máximos")
            return None
        for section in self.sections:
            logger.debug(f"Verificando seção {section['section_name']} - X: {section['x_start']:.2f} a {section['x_end']:.2f}m")
            if (section['x_start'] <= x <= section['x_end'] and section['y_start'] <= y <= section['y_end']):
                logger.debug(f"✅ Seção encontrada: {section['section_name']}")
                return section
        logger.debug("❌ Nenhuma seção encontrada para as coordenadas fornecidas")
        return None

shelf_manager = ShelfManager()

class AnalyticsManager:
    def __init__(self):
        self.MOVEMENT_THRESHOLD = 20.0  # cm/s
        self.DISTANCE_THRESHOLD = 2.0   # metros
        self.HEART_RATE_NORMAL = (60, 100)  # bpm
        self.BREATH_RATE_NORMAL = (12, 20)  # rpm

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

class VitalSignsManager:
    def __init__(self):
        self.SAMPLE_RATE = 20
        self.heart_phase_buffer = []
        self.breath_phase_buffer = []
        self.quality_buffer = []
        self.HEART_BUFFER_SIZE = 20
        self.BREATH_BUFFER_SIZE = 30
        self.QUALITY_BUFFER_SIZE = 10
        self.last_heart_rate = None
        self.last_breath_rate = None
        self.last_quality_score = 0
        self.MIN_QUALITY_SCORE = 0.3
        self.STABILITY_THRESHOLD = 0.4
        self.VALID_RANGES = {
            'heart_rate': (40, 140),
            'breath_rate': (8, 25)
        }
        self.heart_rate_history = []
        self.breath_rate_history = []
        self.HISTORY_SIZE = 10

    def calculate_signal_quality(self, phase_data, distance):
        try:
            if not phase_data or len(phase_data) < 1:
                return 0.0
                
            # Se for um único valor, criar uma lista com ele
            if isinstance(phase_data, (int, float)):
                phase_data = [phase_data]
                
            distance_score = 1.0
            if distance < 30 or distance > 150:
                distance_score = 0.0
            elif distance > 100:
                distance_score = 1.0 - ((distance - 100) / 50)
                
            # Para um único valor, usar uma variância mínima
            variance = 0.1 if len(phase_data) == 1 else np.var(phase_data)
            variance_score = 1.0 / (1.0 + variance * 10)
            
            # Para um único valor, usar uma amplitude mínima
            amplitude = 0.1 if len(phase_data) == 1 else np.ptp(phase_data)
            amplitude_score = 1.0
            if amplitude < 0.01 or amplitude > 1.0:
                amplitude_score = 0.5
                
            quality_score = (distance_score * 0.3 +
                           variance_score * 0.4 +
                           amplitude_score * 0.3)
                           
            self.quality_buffer.append(quality_score)
            if len(self.quality_buffer) > self.QUALITY_BUFFER_SIZE:
                self.quality_buffer.pop(0)
                
            self.last_quality_score = np.mean(self.quality_buffer)
            return self.last_quality_score
            
        except Exception as e:
            logger.error(f"Erro ao calcular qualidade do sinal: {str(e)}")
            return 0.0

    def calculate_vital_signs(self, total_phase, breath_phase, heart_phase, distance):
        try:
            # Converter os valores de fase para listas se forem floats
            if isinstance(heart_phase, (int, float)):
                heart_phase = [heart_phase]
            if isinstance(breath_phase, (int, float)):
                breath_phase = [breath_phase]
                
            quality_score = self.calculate_signal_quality(heart_phase, distance)
            logger.debug(f"Qualidade do sinal: {quality_score:.2f}")
            if quality_score < self.MIN_QUALITY_SCORE:
                logger.debug(f"⚠️ Qualidade do sinal muito baixa: {quality_score:.2f}")
                return None, None
            self.heart_phase_buffer.append(heart_phase)
            self.breath_phase_buffer.append(breath_phase)
            while len(self.heart_phase_buffer) > self.HEART_BUFFER_SIZE:
                self.heart_phase_buffer.pop(0)
            while len(self.breath_phase_buffer) > self.BREATH_BUFFER_SIZE:
                self.breath_phase_buffer.pop(0)
            if len(self.heart_phase_buffer) < self.HEART_BUFFER_SIZE * 0.7:
                logger.debug(f"⏳ Aguardando mais dados ({len(self.heart_phase_buffer)}/{self.HEART_BUFFER_SIZE})")
                return None, None
            heart_weights = np.hamming(len(self.heart_phase_buffer))
            breath_weights = np.hamming(len(self.breath_phase_buffer))
            heart_smooth = np.average(self.heart_phase_buffer, weights=heart_weights)
            breath_smooth = np.average(self.breath_phase_buffer, weights=breath_weights)
            heart_rate = self._calculate_rate_from_phase(
                self.heart_phase_buffer,
                min_freq=self.VALID_RANGES['heart_rate'][0]/60,
                max_freq=self.VALID_RANGES['heart_rate'][1]/60,
                rate_multiplier=60
            )
            breath_rate = self._calculate_rate_from_phase(
                self.breath_phase_buffer,
                min_freq=self.VALID_RANGES['breath_rate'][0]/60,
                max_freq=self.VALID_RANGES['breath_rate'][1]/60,
                rate_multiplier=60
            )
            if heart_rate:
                if self.last_heart_rate:
                    rate_change = abs(heart_rate - self.last_heart_rate) / self.last_heart_rate
                    if rate_change > self.STABILITY_THRESHOLD:
                        logger.debug(f"⚠️ Mudança brusca nos batimentos: {rate_change:.2f}")
                        heart_rate = (heart_rate + self.last_heart_rate) / 2
                    else:
                        self.last_heart_rate = heart_rate
                else:
                    self.last_heart_rate = heart_rate
                self.heart_rate_history.append(heart_rate)
                if len(self.heart_rate_history) > self.HISTORY_SIZE:
                    self.heart_rate_history.pop(0)
            if breath_rate:
                if self.last_breath_rate:
                    rate_change = abs(breath_rate - self.last_breath_rate) / self.last_breath_rate
                    if rate_change > self.STABILITY_THRESHOLD:
                        logger.debug(f"⚠️ Mudança brusca na respiração: {rate_change:.2f}")
                        breath_rate = None
                    else:
                        self.last_breath_rate = breath_rate
                else:
                    self.last_breath_rate = breath_rate
                self.breath_rate_history.append(breath_rate)
                if len(self.breath_rate_history) > self.HISTORY_SIZE:
                    self.breath_rate_history.pop(0)
            if heart_rate and breath_rate:
                logger.debug(f"✅ Medição válida - HR: {heart_rate:.1f} bpm, BR: {breath_rate:.1f} rpm")
            return heart_rate, breath_rate
        except Exception as e:
            logger.error(f"Erro ao calcular sinais vitais: {str(e)}")
            logger.error(traceback.format_exc())
            return None, None

    def _calculate_rate_from_phase(self, phase_data, min_freq, max_freq, rate_multiplier):
        try:
            if not phase_data:
                return None
            phase_mean = np.mean(phase_data)
            centered_phase = np.array(phase_data) - phase_mean
            window = np.hanning(len(centered_phase))
            windowed_phase = centered_phase * window
            fft_result = np.fft.fft(windowed_phase)
            fft_freq = np.fft.fftfreq(len(windowed_phase), d=1/self.SAMPLE_RATE)
            valid_idx = np.where((fft_freq >= min_freq) & (fft_freq <= max_freq))[0]
            if len(valid_idx) == 0:
                return None
            magnitude_spectrum = np.abs(fft_result[valid_idx])
            peak_idx = np.argmax(magnitude_spectrum)
            dominant_freq = fft_freq[valid_idx[peak_idx]]
            peak_magnitude = magnitude_spectrum[peak_idx]
            avg_magnitude = np.mean(magnitude_spectrum)
            if peak_magnitude < 1.5 * avg_magnitude:
                return None
            rate = abs(dominant_freq * rate_multiplier)
            return round(rate, 1)
        except Exception as e:
            logger.error(f"Erro ao calcular taxa a partir da fase: {str(e)}")
            return None

class SerialRadarManager:
    def __init__(self, port=None, baudrate=115200):
        self.port = port or SERIAL_CONFIG['port']
        self.baudrate = baudrate or SERIAL_CONFIG['baudrate']
        self.serial_connection = None
        self.is_running = False
        self.receive_thread = None
        self.db_manager = None
        self.analytics_manager = AnalyticsManager()
        self.vital_signs_manager = VitalSignsManager()
        self.current_session_id = None
        self.last_activity_time = None
        self.SESSION_TIMEOUT = 60  # 1 minuto para identificar novas pessoas
        self.last_valid_data_time = time.time()  # Timestamp do último dado válido
        self.RESET_TIMEOUT = 60  # 1 minuto
        # Buffer para engajamento
        self.engagement_buffer = []
        self.ENGAGEMENT_WINDOW = 1
        self.ENGAGEMENT_DISTANCE = 1.0
        self.ENGAGEMENT_SPEED = 10.0
        self.ENGAGEMENT_MIN_COUNT = 1
        # Parâmetros para detecção de pessoas
        self.last_position = None
        self.POSITION_THRESHOLD = 0.5
        self.MOVEMENT_THRESHOLD = 20.0
        self.session_positions = []

    def _generate_session_id(self):
        """Gera um novo ID de sessão"""
        return str(uuid.uuid4())

    def _check_session_timeout(self):
        """Verifica se a sessão atual expirou"""
        if self.last_activity_time and (time.time() - self.last_activity_time) > self.SESSION_TIMEOUT:
            logger.debug("Sessão expirada, gerando nova sessão")
            self.current_session_id = self._generate_session_id()
            self.last_activity_time = time.time()
            self.session_positions = []  # Limpa histórico de posições
            return True
        return False

    def _is_new_person(self, x, y, move_speed):
        """Verifica se os dados indicam uma nova pessoa"""
        if not self.last_position:
            return True

        last_x, last_y = self.last_position
        distance = math.sqrt((x - last_x)**2 + (y - last_y)**2)
        
        # Se a distância for muito grande ou a velocidade for muito alta, provavelmente é uma nova pessoa
        if distance > self.POSITION_THRESHOLD or move_speed > self.MOVEMENT_THRESHOLD:
            return True
            
        # Verifica se o movimento é consistente com a última posição
        if len(self.session_positions) >= 2:
            last_positions = self.session_positions[-2:]
            avg_speed = sum(p['speed'] for p in last_positions) / len(last_positions)
            if abs(move_speed - avg_speed) > self.MOVEMENT_THRESHOLD:
                return True
                
        return False

    def _update_session(self):
        """Atualiza ou cria uma nova sessão"""
        current_time = time.time()
        
        # Verifica timeout da sessão
        if not self.current_session_id or self._check_session_timeout():
            self.current_session_id = self._generate_session_id()
            self.last_activity_time = current_time
            self.session_positions = []  # Limpa histórico de posições
            logger.debug(f"Nova sessão iniciada: {self.current_session_id}")
        else:
            self.last_activity_time = current_time

    def find_serial_port(self):
        import serial.tools.list_ports
        ports = list(serial.tools.list_ports.comports())
        if not ports:
            logger.error("Nenhuma porta serial encontrada!")
            return None
        for port in ports:
            desc_lower = port.description.lower()
            if any(term in desc_lower for term in
                  ['usb', 'serial', 'uart', 'cp210', 'ch340', 'ft232', 'arduino', 'esp32']):
                logger.info(f"Porta serial encontrada: {port.device} ({port.description})")
                return port.device
        logger.info(f"Usando primeira porta serial disponível: {ports[0].device}")
        return ports[0].device

    def connect(self):
        # Se a porta não existir mais, tenta detectar automaticamente
        if not self.port or not os.path.exists(self.port):
            logger.warning(f"Porta serial {self.port} não encontrada. Tentando detectar automaticamente...")
            detected_port = self.find_serial_port()
            if detected_port:
                self.port = detected_port
                logger.info(f"Porta serial detectada automaticamente: {self.port}")
            else:
                logger.error("Nenhuma porta serial disponível para conexão!")
                return False
        try:
            logger.info(f"Conectando à porta serial {self.port} (baudrate: {self.baudrate})...")
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
            logger.info(f"✅ Conexão serial estabelecida com sucesso!")
            return True
        except Exception as e:
            logger.error(f"❌ Erro ao conectar à porta serial: {str(e)}")
            logger.error(traceback.format_exc())
            return False

    def start(self, db_manager):
        self.db_manager = db_manager
        if not self.connect():
            return False
        self.is_running = True
        self.receive_thread = threading.Thread(target=self.receive_data_loop)
        self.receive_thread.daemon = True
        self.receive_thread.start()
        logger.info("Receptor de dados seriais iniciado!")
        return True

    def stop(self):
        self.is_running = False
        if self.serial_connection:
            try:
                self.serial_connection.close()
            except:
                pass
        if self.receive_thread and self.receive_thread.is_alive():
            self.receive_thread.join(timeout=2)
        logger.info("Receptor de dados seriais parado!")

    def hardware_reset_esp32(self):
        """
        Reinicia a ESP32 via pulso nas linhas DTR/RTS da porta serial.
        Não interfere na conexão principal do radar.
        """
        try:
            logger.warning("[ESP32 RESET] Iniciando reset via DTR/RTS na porta serial...")
            # Fecha a conexão principal se estiver aberta
            was_open = False
            if self.serial_connection and self.serial_connection.is_open:
                self.serial_connection.close()
                was_open = True
            # Abre uma conexão temporária só para reset
            with serial.Serial(self.port, self.baudrate, timeout=1) as ser:
                ser.setDTR(False)
                ser.setRTS(True)
                time.sleep(0.1)
                ser.setDTR(True)
                ser.setRTS(False)
                time.sleep(0.1)
            logger.info("[ESP32 RESET] Pulso de reset enviado com sucesso!")
            # Reabre a conexão principal se estava aberta
            if was_open:
                self.connect()
            return True
        except Exception as e:
            logger.error(f"[ESP32 RESET] Falha ao resetar ESP32: {e}")
            logger.error(traceback.format_exc())
            return False

    def receive_data_loop(self):
        buffer = ""
        message_mode = False
        message_buffer = ""
        target_data_complete = False
        last_data_time = time.time()
        if not hasattr(self, 'last_valid_data_time'):
            self.last_valid_data_time = time.time()
        self.RESET_TIMEOUT = 60  # 1 minuto
        logger.info("\n🔄 Iniciando loop de recebimento de dados...")
        while self.is_running:
            try:
                if not self.serial_connection.is_open:
                    logger.warning("⚠️ Conexão serial fechada, tentando reconectar...")
                    self.connect()
                    time.sleep(1)
                    continue
                in_waiting = self.serial_connection.in_waiting
                if in_waiting is None:
                    in_waiting = 0
                data = self.serial_connection.read(in_waiting or 1)
                if data:
                    last_data_time = time.time()
                    text = data.decode('utf-8', errors='ignore')
                    logger.debug(f"Dados recebidos: {text}")  # Log dos dados brutos
                    buffer += text
                    if '\n' in buffer:
                        lines = buffer.split('\n')
                        buffer = lines[-1]
                        for line in lines[:-1]:
                            line = line.strip()
                            logger.debug(f"Processando linha: {line}")  # Log de cada linha
                            if '-----Human Detected-----' in line:
                                if not message_mode:
                                    message_mode = True
                                    message_buffer = line + '\n'
                                    target_data_complete = False
                            elif message_mode:
                                message_buffer += line + '\n'
                                if 'move_speed:' in line:
                                    target_data_complete = True
                                    logger.debug(f"Mensagem completa recebida:\n{message_buffer}")  # Log da mensagem completa
                                    self.process_radar_data(message_buffer)
                                    self.last_valid_data_time = time.time()  # Atualiza SOMENTE ao processar mensagem completa
                                    message_mode = False
                                    message_buffer = ""
                                    target_data_complete = False
                current_time = time.time()
                logger.warning(f"[DEBUG RESET] Agora: {current_time}, Último dado: {self.last_valid_data_time}, Diferença: {current_time - self.last_valid_data_time}")
                if current_time - self.last_valid_data_time > self.RESET_TIMEOUT:
                    logger.warning("⚠️ Nenhum dado recebido por mais de 1 minuto. Executando reset automático da ESP32 via DTR/RTS...")
                    self.hardware_reset_esp32()
                    self.last_valid_data_time = current_time
                if time.time() - last_data_time > 5:
                    logger.warning("⚠️ Nenhum dado recebido nos últimos 5 segundos")
                    last_data_time = time.time()
                time.sleep(0.01)
            except Exception as e:
                logger.error(f"❌ Erro no loop de recepção: {str(e)}")
                logger.error(traceback.format_exc())
                time.sleep(1)

    def reset_radar(self):
        """Executa um reset no radar"""
        try:
            logger.warning("🔄 [RESET] Iniciando reset do radar por inatividade de dados...")
            # Desconecta o radar
            if self.serial_connection and self.serial_connection.is_open:
                logger.info("[RESET] Fechando conexão serial antes do reset...")
                self.serial_connection.close()
                time.sleep(1)  # Aguarda 1 segundo
            else:
                logger.info("[RESET] Conexão serial já estava fechada.")
            # Reconecta o radar
            logger.info(f"[RESET] Reabrindo conexão serial na porta {self.port}...")
            self.serial_connection = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=1,
                write_timeout=1,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE
            )
            logger.info("[RESET] Conexão serial reestabelecida.")
            # Envia comando de reset (ajuste conforme necessário para seu radar)
            logger.info("[RESET] Enviando comando de reset para o radar...")
            self.serial_connection.write(b'RESET\n')
            time.sleep(2)  # Aguarda 2 segundos para o reset completar
            logger.info("✅ [RESET] Reset do radar concluído com sucesso!")
            return True
        except Exception as e:
            logger.error(f"❌ [RESET] Erro ao resetar o radar: {str(e)}")
            logger.error(traceback.format_exc())
            return False

    def _check_engagement(self, section_id, distance, move_speed):
        # Adiciona leitura ao buffer
        self.engagement_buffer.append({
            'section_id': section_id,
            'distance': distance,
            'move_speed': move_speed,
            'timestamp': time.time()
        })
        # Mantém o buffer no tamanho da janela
        if len(self.engagement_buffer) > self.ENGAGEMENT_WINDOW:
            self.engagement_buffer.pop(0)
        # Filtra leituras válidas
        valid = [e for e in self.engagement_buffer if e['section_id'] == section_id and e['distance'] <= self.ENGAGEMENT_DISTANCE and e['move_speed'] <= self.ENGAGEMENT_SPEED]
        # Engajamento se houver pelo menos ENGAGEMENT_MIN_COUNT leituras consecutivas válidas
        if len(valid) >= self.ENGAGEMENT_MIN_COUNT:
            return True
        return False

    def process_radar_data(self, raw_data):
        data = parse_serial_data(raw_data)
        if not data:
            return

        # Extrair dados relevantes
        x = data.get('x_point', 0)
        y = data.get('y_point', 0)
        move_speed = abs(data.get('dop_index', 0) * RANGE_STEP)
        
        # Verifica se é uma nova pessoa
        if self._is_new_person(x, y, move_speed):
            self.current_session_id = self._generate_session_id()
            self.last_activity_time = time.time()
            self.session_positions = []
            logger.debug(f"Nova pessoa detectada, iniciando sessão: {self.current_session_id}")
        
        # Atualiza posição atual
        self.last_position = (x, y)
        self.session_positions.append({
            'x': x,
            'y': y,
            'speed': move_speed,
            'timestamp': time.time()
        })
        
        # Mantém apenas as últimas 10 posições
        if len(self.session_positions) > 10:
            self.session_positions.pop(0)

        # Atualiza a sessão
        self._update_session()

        # Usar os valores de batimentos e respiração diretamente do radar se disponíveis
        heart_rate = data.get('heart_rate')
        breath_rate = data.get('breath_rate')
        
        # Se não houver valores diretos, calcular usando as fases
        if heart_rate is None or breath_rate is None:
            heart_rate, breath_rate = self.vital_signs_manager.calculate_vital_signs(
                data.get('total_phase', 0),
                data.get('breath_phase', 0),
                data.get('heart_phase', 0),
                data.get('distance', 0)
            )
        distance = data.get('distance', 0)
        if distance == 0:
            x = data.get('x_point', 0)
            y = data.get('y_point', 0)
            distance = (x**2 + y**2)**0.5
        dop_index = data.get('dop_index', 0)
        move_speed = abs(dop_index * RANGE_STEP) if dop_index is not None else 0
        
        converted_data = {
            'session_id': self.current_session_id,
            'x_point': data.get('x_point', 0),
            'y_point': data.get('y_point', 0),
            'move_speed': move_speed,
            'distance': distance,
            'dop_index': dop_index,
            'heart_rate': heart_rate,
            'breath_rate': breath_rate,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        
        section = shelf_manager.get_section_at_position(
            converted_data['x_point'],
            converted_data['y_point'],
            self.db_manager
        )
        
        if section:
            converted_data['section_id'] = section['section_id']
            converted_data['product_id'] = section['product_id']
        else:
            converted_data['section_id'] = None
            converted_data['product_id'] = None
        
        # Lógica de engajamento
        is_engaged = False
        if section:
            is_engaged = self._check_engagement(section['section_id'], distance, move_speed)
        converted_data['is_engaged'] = is_engaged
        
        satisfaction_score, satisfaction_class = self.analytics_manager.calculate_satisfaction_score(
            move_speed, heart_rate, breath_rate, distance
        )
        converted_data['satisfaction_score'] = satisfaction_score
        converted_data['satisfaction_class'] = satisfaction_class

        # Formatação da saída
        output = [
            "\n" + "="*50,
            "📡 DADOS DO RADAR",
            "="*50,
            f"⏰ {converted_data['timestamp']}",
            "-"*50
        ]
        
        if section:
            output.extend([
                f"📍 SEÇÃO: {section['section_name']}",
                f"   Produto ID: {section['product_id']}"
            ])
        else:
            output.extend([
                "📍 SEÇÃO: Fora da área monitorada",
                "   Produto ID: N/A"
            ])
        
        output.extend([
            "-"*50,
            "📊 POSIÇÃO:",
            f"   X: {converted_data['x_point']:>6.2f} m",
            f"   Y: {converted_data['y_point']:>6.2f} m",
            f"   Distância: {converted_data['distance']:>6.2f} m",
            f"   Velocidade: {converted_data['move_speed']:>6.2f} cm/s",
            "-"*50,
            "❤️ SINAIS VITAIS:"
        ])
        
        if heart_rate is not None and breath_rate is not None:
            output.extend([
                f"   Batimentos: {heart_rate:>6.1f} bpm",
                f"   Respiração: {breath_rate:>6.1f} rpm"
            ])
        else:
            output.append("   ⚠️ Aguardando detecção...")
        
        output.extend([
            "-"*50,
            "🎯 ANÁLISE:",
            f"   Engajamento: {'✅ Sim' if is_engaged else '❌ Não'}",
            f"   Score: {converted_data['satisfaction_score']:>6.1f}",
            f"   Classificação: {converted_data['satisfaction_class']}",
            "="*50 + "\n"
        ])
        
        # Exibe a saída formatada
        logger.info("\n".join(output))
        
        if self.db_manager:
            try:
                success = self.db_manager.insert_radar_data(converted_data)
                if success:
                    logger.debug("Dados enviados para o Google Sheets")
                else:
                    logger.error("Falha ao enviar dados para o Google Sheets")
            except Exception as e:
                logger.error(f"Erro ao enviar para o Google Sheets: {str(e)}")
                logger.error(traceback.format_exc())
        else:
            logger.warning("Gerenciador de planilha não disponível")

def main():
    logger.info("Iniciando GoogleSheetsManager...")
    try:
        # Obtém o caminho absoluto do diretório onde o script está localizado
        script_dir = os.path.dirname(os.path.abspath(__file__))
        # Constrói o caminho absoluto para o arquivo de credenciais
        credentials_file_path = os.path.join(script_dir, 'serial_radar', 'credenciais.json')
        gsheets_manager = GoogleSheetsManager(credentials_file_path, 'codigo_rasp')
        logger.info("✅ GoogleSheetsManager iniciado com sucesso!")
    except Exception as e:
        logger.error(f"❌ Erro ao criar instância do GoogleSheetsManager: {e}")
        logger.error(traceback.format_exc())
        return
    
    # Definindo a porta serial diretamente
    port = '/dev/ttyACM0'
    baudrate = int(os.getenv("SERIAL_BAUDRATE", "115200"))
    radar_manager = SerialRadarManager(port, baudrate)
    try:
        logger.info(f"Iniciando SerialRadarManager...")
        success = radar_manager.start(gsheets_manager)
        if not success:
            logger.error("❌ Falha ao iniciar o gerenciador de radar serial")
            return
        logger.info("="*50)
        logger.info("🚀 Sistema Radar Serial iniciado com sucesso!")
        logger.info(f"📡 Porta serial: {radar_manager.port}")
        logger.info(f"📡 Baudrate: {radar_manager.baudrate}")
        logger.info("⚡ Pressione Ctrl+C para encerrar")
        logger.info("="*50)
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Encerrando por interrupção do usuário...")
    finally:
        radar_manager.stop()
        logger.info("Sistema encerrado!")

if __name__ == "__main__":
    main() 
