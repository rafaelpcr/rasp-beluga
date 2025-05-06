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
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('radar_serial.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('radar_serial_app')

load_dotenv()

SERIAL_CONFIG = {
    'port': os.getenv('SERIAL_PORT', '/dev/ttyUSB0'),
    'baudrate': int(os.getenv('SERIAL_BAUDRATE', 115200))
}
RANGE_STEP = 2.5

class GoogleSheetsManager:
    def __init__(self, creds_path, spreadsheet_name, worksheet_name='Sheet1'):
        SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
        self.creds = Credentials.from_service_account_file(creds_path, scopes=SCOPES)
        self.gc = gspread.authorize(self.creds)
        self.spreadsheet = self.gc.open(spreadsheet_name)
        self.worksheet = self.spreadsheet.worksheet(worksheet_name)

    def insert_radar_data(self, data):
        try:
            row = [
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
    # ... (mesma função do radar_serial.py)
    # (copiar função completa aqui)
    try:
        x_pattern = r'x_point:\s*([-]?\d+\.\d+)'
        y_pattern = r'y_point:\s*([-]?\d+\.\d+)'
        dop_pattern = r'dop_index:\s*([-]?\d+)'
        cluster_pattern = r'cluster_index:\s*(\d+)'
        speed_pattern = r'move_speed:\s*([-]?\d+\.\d+)\s*cm/s'
        total_phase_pattern = r'total_phase:\s*([-]?\d+\.\d+)'
        breath_phase_pattern = r'breath_phase:\s*([-]?\d+\.\d+)'
        heart_phase_pattern = r'heart_phase:\s*([-]?\d+\.\d+)'
        breath_rate_pattern = r'breath_rate:\s*([-]?\d+\.\d+)'
        heart_rate_pattern = r'heart_rate:\s*([-]?\d+\.\d+)'
        distance_pattern = r'distance:\s*([-]?\d+\.\d+)'
        if '-----Human Detected-----' not in raw_data:
            return None
        if 'Target 1:' not in raw_data:
            return None
        x_match = re.search(x_pattern, raw_data)
        y_match = re.search(y_pattern, raw_data)
        dop_match = re.search(dop_pattern, raw_data)
        cluster_match = re.search(cluster_pattern, raw_data)
        speed_match = re.search(speed_pattern, raw_data)
        total_phase_match = re.search(total_phase_pattern, raw_data)
        breath_phase_match = re.search(breath_phase_pattern, raw_data)
        heart_phase_match = re.search(heart_phase_pattern, raw_data)
        breath_rate_match = re.search(breath_rate_pattern, raw_data)
        heart_rate_match = re.search(heart_rate_pattern, raw_data)
        distance_match = re.search(distance_pattern, raw_data)
        if x_match and y_match:
            data = {
                'x_point': float(x_match.group(1)),
                'y_point': float(y_match.group(1)),
                'dop_index': int(dop_match.group(1)) if dop_match else 0,
                'cluster_index': int(cluster_match.group(1)) if cluster_match else 0,
                'move_speed': float(speed_match.group(1)) if speed_match else 0.0,
                'total_phase': float(total_phase_match.group(1)) if total_phase_match else 0.0,
                'breath_phase': float(breath_phase_match.group(1)) if breath_phase_match else 0.0,
                'heart_phase': float(heart_phase_match.group(1)) if heart_phase_match else 0.0,
                'breath_rate': float(breath_rate_match.group(1)) if breath_rate_match else None,
                'heart_rate': float(heart_rate_match.group(1)) if heart_rate_match else None,
                'distance': float(distance_match.group(1)) if distance_match else None
            }
            if data['distance'] is None:
                data['distance'] = math.sqrt(data['x_point']**2 + data['y_point']**2) * 100
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
        # Constantes para mapeamento de seções
        self.SECTION_WIDTH = 50  # Largura de cada seção em centímetros
        self.SECTION_HEIGHT = 30  # Altura de cada seção em centímetros
        self.MAX_SECTIONS_X = 4    # Número máximo de seções na horizontal
        self.MAX_SECTIONS_Y = 3    # Número máximo de seções na vertical
        self.SCALE_FACTOR = 100    # Fator de escala para ajustar coordenadas do radar
        # Seções padrão (em memória)
        self.sections = [
            {
                'section_id': 1,
                'section_name': 'Granolas Premium',
                'product_id': '1',
                'x_start': 0.0,
                'y_start': 0.0,
                'x_end': 0.5,
                'y_end': 0.3
            },
            {
                'section_id': 2,
                'section_name': 'Mix de Frutas Secas',
                'product_id': '2',
                'x_start': 0.5,
                'y_start': 0.0,
                'x_end': 1.0,
                'y_end': 0.3
            },
            {
                'section_id': 3,
                'section_name': 'Barras de Cereais',
                'product_id': '3',
                'x_start': 1.0,
                'y_start': 0.0,
                'x_end': 1.5,
                'y_end': 0.3
            }
        ]

    def adjust_scale(self, value):
        """Ajusta a escala das coordenadas do radar"""
        return value * self.SCALE_FACTOR

    def get_section_at_position(self, x, y, db_manager=None):
        """Identifica a seção baseada nas coordenadas (x, y)"""
        x_adjusted = self.adjust_scale(x) / 100  # Volta para metros
        y_adjusted = self.adjust_scale(y) / 100
        for section in self.sections:
            if (section['x_start'] <= x_adjusted <= section['x_end'] and
                section['y_start'] <= y_adjusted <= section['y_end']):
                return section
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
            if not phase_data or len(phase_data) < 5:
                return 0.0
            distance_score = 1.0
            if distance < 30 or distance > 150:
                distance_score = 0.0
            elif distance > 100:
                distance_score = 1.0 - ((distance - 100) / 50)
            variance = np.var(phase_data)
            variance_score = 1.0 / (1.0 + variance * 10)
            amplitude = np.ptp(phase_data)
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
        if not self.port:
            logger.error("Porta serial não especificada!")
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

    def receive_data_loop(self):
        buffer = ""
        message_mode = False
        message_buffer = ""
        target_data_complete = False
        last_data_time = time.time()
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
                    buffer += text
                    if '\n' in buffer:
                        lines = buffer.split('\n')
                        buffer = lines[-1]
                        for line in lines[:-1]:
                            line = line.strip()
                            if '-----Human Detected-----' in line:
                                message_mode = True
                                message_buffer = line + '\n'
                                target_data_complete = False
                            elif message_mode:
                                message_buffer += line + '\n'
                                if 'distance:' in line:
                                    target_data_complete = True
                                    self.process_radar_data(message_buffer)
                                    message_mode = False
                                    message_buffer = ""
                                    target_data_complete = False
                if time.time() - last_data_time > 5:
                    logger.warning("⚠️ Nenhum dado recebido nos últimos 5 segundos")
                    last_data_time = time.time()
                time.sleep(0.01)
            except Exception as e:
                logger.error(f"❌ Erro no loop de recepção: {str(e)}")
                logger.error(traceback.format_exc())
                time.sleep(1)

    def process_radar_data(self, raw_data):
        try:
            data = parse_serial_data(raw_data)
            if not data:
                return
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
                logger.debug(f"Distância calculada: {distance:.2f}cm")
            dop_index = data.get('dop_index', 0)
            move_speed = abs(dop_index * RANGE_STEP) if dop_index is not None else 0
            logger.debug(f"Velocidade calculada: {move_speed:.2f}cm/s (dop_index: {dop_index})")
            converted_data = {
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
            is_engaged = False
            engagement_prob = 0.0
            converted_data['is_engaged'] = is_engaged
            satisfaction_score = 50.0
            converted_data['satisfaction_score'] = satisfaction_score
            if satisfaction_score >= 85:
                converted_data['satisfaction_class'] = "MUITO_POSITIVA"
            elif satisfaction_score >= 70:
                converted_data['satisfaction_class'] = "POSITIVA"
            elif satisfaction_score >= 50:
                converted_data['satisfaction_class'] = "NEUTRA"
            elif satisfaction_score >= 30:
                converted_data['satisfaction_class'] = "NEGATIVA"
            else:
                converted_data['satisfaction_class'] = "MUITO_NEGATIVA"
            print("\n" + "="*50)
            print("📡 DADOS DO RADAR DETECTADOS")
            print("="*50)
            print(f"⏰ Timestamp: {converted_data['timestamp']}")
            print("")
            if section:
                print(f"📍 LOCALIZAÇÃO:")
                print(f"   Seção: {section['section_name']}")
                print(f"   Produto: {section['product_id']}")
            else:
                print(f"📍 LOCALIZAÇÃO:")
                print("   ⚠️ Fora das seções monitoradas")
                print("   Produto: N/A")
            print("")
            print(f"📊 DADOS DE POSIÇÃO:")
            print(f"   Distância: {converted_data['distance']:.2f} cm")
            print(f"   Velocidade: {converted_data['move_speed']:.2f} cm/s")
            print("")
            print(f"❤️ SINAIS VITAIS:")
            if heart_rate is not None and breath_rate is not None:
                print(f"   Batimentos: {heart_rate:.1f} bpm")
                print(f"   Respiração: {breath_rate:.1f} rpm")
            else:
                print("   ⚠️ Aguardando detecção de sinais vitais...")
            print("")
            print(f"🎯 ANÁLISE:")
            print(f"   Engajado: {'✅ Sim' if is_engaged else '❌ Não'}")
            print(f"   Score: {converted_data['satisfaction_score']:.1f}")
            print(f"   Classificação: {converted_data['satisfaction_class']}")
            print("="*50)
            print("")
            if self.db_manager:
                try:
                    success = self.db_manager.insert_radar_data(converted_data)
                    if success:
                        logger.debug("✅ Dados enviados para o Google Sheets!")
                    else:
                        logger.error("❌ Falha ao enviar dados para o Google Sheets")
                except Exception as e:
                    logger.error(f"❌ Erro ao enviar para o Google Sheets: {str(e)}")
                    logger.error(traceback.format_exc())
            else:
                logger.warning("⚠️ Gerenciador de planilha não disponível")
        except Exception as e:
            logger.error(f"❌ Erro ao processar dados: {str(e)}")
            logger.error(traceback.format_exc())

def main():
    logger.info("Iniciando GoogleSheetsManager...")
    try:
        gsheets_manager = GoogleSheetsManager('serial_radar/credenciais.json', 'codigo_rasp')
        logger.info("✅ GoogleSheetsManager iniciado com sucesso!")
    except Exception as e:
        logger.error(f"❌ Erro ao criar instância do GoogleSheetsManager: {e}")
        logger.error(traceback.format_exc())
        return
    port = os.getenv("SERIAL_PORT")
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
