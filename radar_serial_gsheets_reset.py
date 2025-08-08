import requests
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
import json

# Configuração básica de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('radar_serial_supabase.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('radar_serial_supabase_app')

# Configurando o nível de log para outros módulos
logging.getLogger('urllib3').setLevel(logging.WARNING)
logging.getLogger('requests').setLevel(logging.WARNING)

load_dotenv()

SERIAL_CONFIG = {
    'port': os.getenv('SERIAL_PORT', '/dev/ttyACM0'),
    'baudrate': int(os.getenv('SERIAL_BAUDRATE', 115200))
}

# Configurações do Supabase
SUPABASE_CONFIG = {
    'url': os.getenv('SUPABASE_URL', ''),
    'anon_key': os.getenv('SUPABASE_ANON_KEY', ''),
    'edge_function_url': os.getenv('SUPABASE_EDGE_FUNCTION_URL', ''),
    'retry_attempts': int(os.getenv('SUPABASE_RETRY_ATTEMPTS', 3)),
    'retry_delay': int(os.getenv('SUPABASE_RETRY_DELAY', 2))
}

RANGE_STEP = 2.5

class SupabaseManager:
    def __init__(self, supabase_url, supabase_anon_key, edge_function_url):
        self.supabase_url = supabase_url
        self.supabase_anon_key = supabase_anon_key
        self.edge_function_url = edge_function_url
        self.session = requests.Session()
        
        # Configurar headers padrão
        self.session.headers.update({
            'Content-Type': 'application/json',
            'apikey': self.supabase_anon_key,
            'Authorization': f'Bearer {self.supabase_anon_key}'
        })
        
        logger.info(f"✅ [SUPABASE_INIT] SupabaseManager inicializado!")
        logger.info(f"🔗 [SUPABASE_INIT] URL: {self.supabase_url}")
        logger.info(f"🔗 [SUPABASE_INIT] Edge Function: {self.edge_function_url}")

    def insert_radar_data(self, data):
        try:
            # Preparar dados para inserção direta na tabela
            table_data = {
                'session_id': data.get('session_id'),
                'timestamp': data.get('timestamp'),
                'x_point': data.get('x_point'),
                'y_point': data.get('y_point'),
                'move_speed': int(data.get('move_speed', 0)),  # Converter para integer
                'heart_rate': int(data.get('heart_rate', 0)) if data.get('heart_rate') else None,  # Converter para integer
                'breath_rate': int(data.get('breath_rate', 0)) if data.get('breath_rate') else None,  # Converter para integer
                'distance': data.get('distance'),
                'section_id': data.get('section_id'),
                'product_id': data.get('product_id'),
                'satisfaction_score': int(data.get('satisfaction_score', 0)),  # Converter para integer
                'satisfaction_class': data.get('satisfaction_class'),
                'is_engaged': data.get('is_engaged')
            }
            
            # Verificar se há valores None ou problemáticos
            problematic_values = []
            for key, value in table_data.items():
                if value is None:
                    problematic_values.append(f"{key}: None")
                elif isinstance(value, (int, float)) and (value != value):  # NaN check
                    problematic_values.append(f"{key}: NaN")
                elif isinstance(value, str) and len(value) > 1000:
                    problematic_values.append(f"{key}: string muito longa ({len(value)} chars)")
            
            if problematic_values:
                logger.warning(f"⚠️ [SUPABASE] Valores problemáticos encontrados: {problematic_values}")
            
            # URL direta para a tabela
            table_url = f"{self.supabase_url}/rest/v1/radar_events"
            
            # Headers para inserção direta
            headers = {
                'Content-Type': 'application/json',
                'apikey': self.supabase_anon_key,
                'Authorization': f'Bearer {self.supabase_anon_key}',
                'Prefer': 'return=minimal'
            }
            
            # Tentativas de envio com retry
            for attempt in range(SUPABASE_CONFIG['retry_attempts']):
                try:
                    response = self.session.post(
                        table_url,
                        json=table_data,
                        headers=headers,
                        timeout=10
                    )
                    
                    if response.status_code == 201:
                        logger.info('✅ Dados inseridos diretamente na tabela radar_events!')
                        return True
                    else:
                        logger.warning(f"⚠️ [SUPABASE] Status code {response.status_code}: {response.text}")
                        if attempt < SUPABASE_CONFIG['retry_attempts'] - 1:
                            time.sleep(SUPABASE_CONFIG['retry_delay'])
                            continue
                        else:
                            logger.error(f"❌ [SUPABASE] Falha após {SUPABASE_CONFIG['retry_attempts']} tentativas")
                            return False
                            
                except requests.exceptions.Timeout:
                    logger.warning(f"⚠️ [SUPABASE] Timeout na tentativa {attempt + 1}")
                    if attempt < SUPABASE_CONFIG['retry_attempts'] - 1:
                        time.sleep(SUPABASE_CONFIG['retry_delay'])
                        continue
                    else:
                        logger.error("❌ [SUPABASE] Timeout após todas as tentativas")
                        return False
                        
                except requests.exceptions.ConnectionError:
                    logger.warning(f"⚠️ [SUPABASE] Erro de conexão na tentativa {attempt + 1}")
                    if attempt < SUPABASE_CONFIG['retry_attempts'] - 1:
                        time.sleep(SUPABASE_CONFIG['retry_delay'])
                        continue
                    else:
                        logger.error("❌ [SUPABASE] Erro de conexão após todas as tentativas")
                        return False
            
            return False
            
        except Exception as e:
            logger.error(f'❌ [SUPABASE] Erro ao enviar dados para o Supabase: {str(e)}')
            logger.error(f'❌ [SUPABASE] Tipo do erro: {type(e)}')
            logger.error(f'❌ [SUPABASE] Dados que causaram o erro: {data}')
            logger.error(traceback.format_exc())
            return False

    def test_connection(self):
        """Testa a conectividade com o Supabase"""
        try:
            # Teste simples de conectividade
            test_payload = {
                'radar_data': {
                    'session_id': 'test_connection',
                    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'x_point': 0.0,
                    'y_point': 0.0,
                    'move_speed': 0.0,
                    'heart_rate': 0.0,
                    'breath_rate': 0.0,
                    'distance': 0.0,
                    'section_id': None,
                    'product_id': None,
                    'satisfaction_score': 0.0,
                    'satisfaction_class': 'TEST',
                    'is_engaged': False
                }
            }
            
            response = self.session.post(
                self.edge_function_url,
                json=test_payload,
                timeout=5
            )
            
            if response.status_code == 200:
                logger.info("✅ [SUPABASE] Teste de conectividade bem-sucedido!")
                return True
            else:
                logger.error(f"❌ [SUPABASE] Teste de conectividade falhou: {response.status_code}")
                return False
                
        except Exception as e:
            logger.error(f"❌ [SUPABASE] Erro no teste de conectividade: {str(e)}")
            return False 

def parse_serial_data(raw_data):
    try:
        # Verificação detalhada dos marcadores
        has_human_detected = '-----Human Detected-----' in raw_data
        has_target_1 = 'Target 1:' in raw_data
        
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
                'section_name': 'Seção 1',
                'product_id': '1',
                'x_start': 0.0,
                'y_start': 0.0,
                'x_end': 0.5,
                'y_end': 1.5
            },
            {
                'section_id': 2,
                'section_name': 'Seção 2',
                'product_id': '2',
                'x_start': 0.5,
                'y_start': 0.0,
                'x_end': 1.0,
                'y_end': 1.5
            },
            {
                'section_id': 3,
                'section_name': 'Seção 3',
                'product_id': '3',
                'x_start': 1.0,
                'y_start': 0.0,
                'x_end': 1.5,
                'y_end': 1.5
            }
        ]

    def get_section_at_position(self, x, y, db_manager=None):
        if x < -1.0 or x > 1.0 or y < 0 or y > 1.5:
            return None
        for section in self.sections:
            if (section['x_start'] <= x <= section['x_end'] and section['y_start'] <= y <= section['y_end']):
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
            # Considera NEUTRA se algum valor for None ou 0 (ausência de leitura)
            if heart_rate is None or breath_rate is None or heart_rate == 0 or breath_rate == 0:
                return (60.0, "NEUTRA")

            # MUITO_POSITIVA
            if (65 <= heart_rate <= 90 and 13 <= breath_rate <= 18 and move_speed < 6):
                return (95.0, "MUITO_POSITIVA")
            # POSITIVA
            elif (60 <= heart_rate <= 100 and 12 <= breath_rate <= 20 and move_speed < 12):
                return (80.0, "POSITIVA")
            # NEUTRA
            elif (55 <= heart_rate <= 110 and 10 <= breath_rate <= 22 and move_speed < 25):
                return (60.0, "NEUTRA")
            # NEGATIVA
            else:
                return (20.0, "NEGATIVA")
        except Exception as e:
            logger.error(f"Erro ao calcular satisfação: {str(e)}")
            return (60.0, "NEUTRA")

class VitalSignsManager:
    def __init__(self):
        self.SAMPLE_RATE = 20
        # Inicializa buffers com tamanho máximo para evitar crescimento indefinido
        self.HEART_BUFFER_SIZE = 20
        self.BREATH_BUFFER_SIZE = 30
        self.QUALITY_BUFFER_SIZE = 10
        self.HISTORY_SIZE = 10
        
        # Inicializa buffers com tamanho máximo
        self.heart_phase_buffer = [0.0] * self.HEART_BUFFER_SIZE
        self.breath_phase_buffer = [0.0] * self.BREATH_BUFFER_SIZE
        self.quality_buffer = [0.0] * self.QUALITY_BUFFER_SIZE
        self.heart_rate_history = [0.0] * self.HISTORY_SIZE
        self.breath_rate_history = [0.0] * self.HISTORY_SIZE
        
        # Contadores para controle de buffer circular
        self.heart_buffer_index = 0
        self.breath_buffer_index = 0
        self.quality_buffer_index = 0
        self.heart_history_index = 0
        self.breath_history_index = 0
        
        self.last_heart_rate = None
        self.last_breath_rate = None
        self.last_quality_score = 0
        self.MIN_QUALITY_SCORE = 0.3
        self.STABILITY_THRESHOLD = 0.4
        self.VALID_RANGES = {
            'heart_rate': (40, 140),
            'breath_rate': (8, 25)
        }

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
                           
            # Buffer circular para qualidade
            self.quality_buffer[self.quality_buffer_index] = quality_score
            self.quality_buffer_index = (self.quality_buffer_index + 1) % self.QUALITY_BUFFER_SIZE
                
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
            if quality_score < self.MIN_QUALITY_SCORE:
                return None, None
            # Buffer circular para fases
            self.heart_phase_buffer[self.heart_buffer_index] = heart_phase
            self.breath_phase_buffer[self.breath_buffer_index] = breath_phase
            
            self.heart_buffer_index = (self.heart_buffer_index + 1) % self.HEART_BUFFER_SIZE
            self.breath_buffer_index = (self.breath_buffer_index + 1) % self.BREATH_BUFFER_SIZE
            
            # Verifica se temos dados suficientes (70% do buffer preenchido)
            heart_data_count = min(self.heart_buffer_index, self.HEART_BUFFER_SIZE)
            if heart_data_count < self.HEART_BUFFER_SIZE * 0.7:
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
                        heart_rate = (heart_rate + self.last_heart_rate) / 2
                    else:
                        self.last_heart_rate = heart_rate
                else:
                    self.last_heart_rate = heart_rate
                # Buffer circular para histórico de batimentos
                self.heart_rate_history[self.heart_history_index] = heart_rate
                self.heart_history_index = (self.heart_history_index + 1) % self.HISTORY_SIZE
            if breath_rate:
                if self.last_breath_rate:
                    rate_change = abs(breath_rate - self.last_breath_rate) / self.last_breath_rate
                    if rate_change > self.STABILITY_THRESHOLD:
                        breath_rate = None
                    else:
                        self.last_breath_rate = breath_rate
                else:
                    self.last_breath_rate = breath_rate
                # Buffer circular para histórico de respiração
                self.breath_rate_history[self.breath_history_index] = breath_rate
                self.breath_history_index = (self.breath_history_index + 1) % self.HISTORY_SIZE
            return heart_rate, breath_rate
        except Exception as e:
            logger.error(f"Erro ao calcular sinais vitais: {str(e)}")
            logger.error(traceback.format_exc())
            return None, None

    def _calculate_rate_from_phase(self, phase_data, min_freq, max_freq, rate_multiplier):
        try:
            if not phase_data:
                return None
            
            # Filtra dados válidos (remove zeros)
            valid_data = [x for x in phase_data if x != 0.0]
            if len(valid_data) < 3:  # Mínimo de dados para FFT
                return None
                
            phase_mean = np.mean(valid_data)
            centered_phase = np.array(valid_data) - phase_mean
            
            # Aplica janela de Hamming para melhorar FFT
            window = np.hanning(len(centered_phase))
            windowed_phase = centered_phase * window
            
            # FFT otimizada - só calcula se necessário
            fft_result = np.fft.fft(windowed_phase)
            fft_freq = np.fft.fftfreq(len(windowed_phase), d=1/self.SAMPLE_RATE)
            
            # Filtra frequências válidas
            valid_idx = np.where((fft_freq >= min_freq) & (fft_freq <= max_freq))[0]
            if len(valid_idx) == 0:
                return None
                
            magnitude_spectrum = np.abs(fft_result[valid_idx])
            peak_idx = np.argmax(magnitude_spectrum)
            dominant_freq = fft_freq[valid_idx[peak_idx]]
            peak_magnitude = magnitude_spectrum[peak_idx]
            avg_magnitude = np.mean(magnitude_spectrum)
            
            # Verifica se o pico é significativo
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
        
        # Sistema de limpeza de memória
        self.last_memory_cleanup = time.time()
        self.MEMORY_CLEANUP_INTERVAL = 300  # 5 minutos
        
        # Contadores para debug
        self.messages_received = 0
        self.messages_processed = 0
        self.messages_failed = 0
        
        # Sistema de retry para reconexões
        self.consecutive_errors = 0
        self.MAX_CONSECUTIVE_ERRORS = 5
        self.last_error_time = 0

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
            logger.warning(f"⚠️ Porta serial {self.port} não encontrada. Tentando detectar automaticamente...")
            
            detected_port = self.find_serial_port()
            if detected_port:
                self.port = detected_port
                logger.info(f"✅ Porta serial detectada automaticamente: {self.port}")
            else:
                logger.error("❌ Nenhuma porta serial disponível para conexão!")
                return False
        
        try:
            logger.info(f"🔄 Conectando à porta serial {self.port} (baudrate: {self.baudrate})...")
            
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
            logger.error(f"🔍 [START] Falha na conexão serial")
            return False
        
        self.is_running = True
        self.receive_thread = threading.Thread(target=self.receive_data_loop)
        self.receive_thread.daemon = True
        self.receive_thread.start()
        
        logger.info("✅ Receptor de dados seriais iniciado!")
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
        last_data_time = time.time()
        if not hasattr(self, 'last_valid_data_time'):
            self.last_valid_data_time = time.time()
        self.RESET_TIMEOUT = 300  # 5 minutos (mais tolerante com heartbeat)
        logger.info("\n🔄 Iniciando loop de recebimento de dados...")
        logger.info(f"🔍 [SERIAL] Aguardando dados da ESP32...")

        bloco_buffer = ""
        coletando_bloco = False

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

                    while '\n' in buffer:
                        line, buffer = buffer.split('\n', 1)
                        line = line.strip('\r')  # Remove \r também
                        
                        # Detecta heartbeat do ESP32
                        if 'HEARTBEAT: Sistema ativo' in line:
                            logger.debug("💓 [SERIAL] Heartbeat recebido - ESP32 ativo")
                            last_data_time = time.time()  # Atualiza timestamp de dados
                            continue
                        
                        # Detecta se ESP32 entrou em modo download
                        if 'waiting for download' in line or 'DOWNLOAD(' in line:
                            logger.warning("⚠️ [SERIAL] ESP32 entrou em modo download! Aguardando reinicialização...")
                            coletando_bloco = False
                            bloco_buffer = ""
                            time.sleep(5)  # Aguarda 5 segundos para ESP32 reiniciar
                            continue
                        
                        # Reduz logs excessivos - só loga quando detecta pessoa
                        if '-----Human Detected-----' in line:
                            logger.debug(f"[SERIAL] Bloco de dados iniciado")
                            coletando_bloco = True
                            bloco_buffer = line + "\n"
                        elif coletando_bloco:
                            if line.strip() == "":
                                # Linha em branco: fim do bloco!
                                logger.debug(f"[SERIAL] Processando bloco de dados")
                                self.process_radar_data(bloco_buffer)
                                coletando_bloco = False
                                bloco_buffer = ""
                            else:
                                bloco_buffer += line + "\n"

                current_time = time.time()
                if current_time - self.last_valid_data_time > self.RESET_TIMEOUT:
                    logger.warning("⚠️ Nenhum dado ou heartbeat recebido por mais de 5 minutos. Executando reset automático da ESP32 via DTR/RTS...")
                    self.hardware_reset_esp32()
                    self.last_valid_data_time = current_time

                # Limpeza periódica de memória
                current_time = time.time()
                if current_time - self.last_memory_cleanup > self.MEMORY_CLEANUP_INTERVAL:
                    self._cleanup_memory()
                    self.last_memory_cleanup = current_time
                
                if time.time() - last_data_time > 30:
                    logger.warning("⚠️ Nenhum dado ou heartbeat recebido nos últimos 30 segundos")
                    last_data_time = time.time()

                time.sleep(0.01)
            except (OSError, IOError) as e:
                error_msg = str(e).lower()
                error_code = str(e)
                current_time = time.time()
                
                # Incrementa contador de erros consecutivos
                if current_time - self.last_error_time < 60:  # Erro nos últimos 60 segundos
                    self.consecutive_errors += 1
                else:
                    self.consecutive_errors = 1  # Reset se passou muito tempo
                
                self.last_error_time = current_time
                
                # Trata diferentes tipos de erro de I/O
                if ('device not configured' in error_msg or 'errno 6' in error_msg or 
                    'input/output error' in error_msg or 'errno 5' in error_msg):
                    
                    logger.error(f"❌ [SERIAL] Erro de I/O detectado: {e} (Erro #{self.consecutive_errors})")
                    
                    # Se muitos erros consecutivos, aguarda mais tempo
                    if self.consecutive_errors >= self.MAX_CONSECUTIVE_ERRORS:
                        logger.warning(f"⚠️ [SERIAL] Muitos erros consecutivos ({self.consecutive_errors}), aguardando 30 segundos...")
                        time.sleep(30)
                        self.consecutive_errors = 0  # Reset contador
                    else:
                        logger.info("🔄 [SERIAL] Tentando reconectar automaticamente...")
                        
                        # Fecha conexão corrompida
                        try:
                            if self.serial_connection:
                                self.serial_connection.close()
                        except:
                            pass
                        
                        # Aguarda um pouco antes de reconectar
                        time.sleep(3)
                        
                        # Tenta reconectar
                        if self.connect():
                            logger.info("✅ [SERIAL] Reconexão bem-sucedida!")
                            self.consecutive_errors = 0  # Reset contador de sucesso
                        else:
                            logger.error("❌ [SERIAL] Falha na reconexão, aguardando 15 segundos...")
                            time.sleep(15)
                    
                    continue
                else:
                    # Outro tipo de erro de I/O
                    logger.error(f"❌ [SERIAL] Erro de I/O desconhecido: {e}")
                    time.sleep(2)
                    continue
                    
            except Exception as e:
                logger.error(f"❌ Erro no loop de recepção: {str(e)}")
                logger.error(traceback.format_exc())
                time.sleep(1)

    def _cleanup_memory(self):
        """Limpeza periódica de memória para evitar vazamentos"""
        try:
            # Força coleta de lixo
            import gc
            gc.collect()
            
            # Limpa buffers antigos se necessário
            if len(self.session_positions) > 10:
                self.session_positions = self.session_positions[-10:]
            
            # Log de status de memória
            logger.debug(f"[MEMORY] Limpeza executada - Sessões ativas: {len(self.session_positions)}")
            
        except Exception as e:
            logger.error(f"[MEMORY] Erro na limpeza: {str(e)}")

    def _check_engagement(self, section_id, distance, move_speed):
        # Engajamento: basta a última leitura ser válida
        if section_id is not None and distance <= self.ENGAGEMENT_DISTANCE and move_speed <= self.ENGAGEMENT_SPEED:
            return True
        return False

    def process_radar_data(self, raw_data):
        # Novo parser para o formato mostrado na imagem
        def parse_radar_text_block(text):
            lines = text.strip().split('\n')
            data = {}
            for line in lines:
                if ':' in line:
                    key, value = line.split(':', 1)
                    key = key.strip().lower().replace(' ', '_')
                    value = value.strip().replace(' cm/s', '')
                    try:
                        data[key] = float(value)
                    except ValueError:
                        try:
                            data[key] = int(value)
                        except ValueError:
                            data[key] = value
            # Renomear para os nomes esperados
            return {
                'x_point': data.get('x_point', 0),
                'y_point': data.get('y_point', 0),
                'move_speed': data.get('move_speed', 0),
                'heart_rate': data.get('heart_rate', None),
                'breath_rate': data.get('breath_rate', None),
                'distance': data.get('distance', 0),
                'dop_index': data.get('dop_index', 0),
                'total_phase': data.get('total_phase', 0),
                'breath_phase': data.get('breath_phase', 0),
                'heart_phase': data.get('heart_phase', 0),
                'cluster_index': data.get('cluster_index', 0),
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
        # Detecta se é o formato texto do radar
        if '-----Human Detected-----' in raw_data and 'Target 1:' in raw_data:
            data = parse_radar_text_block(raw_data)
        else:
            # Tenta JSON ou parser antigo
            try:
                import json
                json_obj = json.loads(raw_data)
                if 'active_people' in json_obj and json_obj['active_people']:
                    person = json_obj['active_people'][0]
                    data = {
                        'x_point': float(person.get('x_pos', 0)),
                        'y_point': float(person.get('y_pos', 0)),
                        'distance': float(person.get('distance_raw', 0)),
                        'confidence': float(person.get('confidence', 0)),
                        'move_speed': 0.0,
                        'heart_rate': None,
                        'breath_rate': None,
                        'dop_index': 0,
                        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    }
                else:
                    logger.warning('[PROCESS] JSON recebido não contém pessoa ativa.')
                    return
            except Exception:
                data = parse_serial_data(raw_data)
                if not data:
                    logger.warning(f"❌ [PROCESS] Mensagem falhou no parse! Total de falhas: {self.messages_failed}")
                    self.messages_failed += 1
                    return
        self.messages_processed += 1
        logger.info(f"✅ [PROCESS] Mensagem processada com sucesso! Total processadas: {self.messages_processed}")
        x = data.get('x_point', 0)
        y = data.get('y_point', 0)
        move_speed = abs(data.get('dop_index', 0) * RANGE_STEP) if 'dop_index' in data else data.get('move_speed', 0)
        if self._is_new_person(x, y, move_speed):
            self.current_session_id = self._generate_session_id()
            self.last_activity_time = time.time()
            self.session_positions = []
        self.last_position = (x, y)
        # Buffer circular para posições de sessão (máximo 10 posições)
        if len(self.session_positions) >= 10:
            self.session_positions.pop(0)  # Remove a posição mais antiga
        
        self.session_positions.append({
            'x': x,
            'y': y,
            'speed': move_speed,
            'timestamp': time.time()
        })
        self._update_session()
        heart_rate = data.get('heart_rate')
        breath_rate = data.get('breath_rate')
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
        dop_index = data.get('dop_index', 0) if 'dop_index' in data else 0
        move_speed = abs(dop_index * RANGE_STEP) if dop_index is not None else data.get('move_speed', 0)
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
        is_engaged = False
        if section:
            is_engaged = self._check_engagement(section['section_id'], distance, move_speed)
        converted_data['is_engaged'] = is_engaged
        satisfaction_result = self.analytics_manager.calculate_satisfaction_score(
            move_speed, heart_rate, breath_rate, distance
        )
        converted_data['satisfaction_score'] = satisfaction_result[0]
        converted_data['satisfaction_class'] = satisfaction_result[1]
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
        logger.info("\n".join(output))
        if self.db_manager:
            try:
                success = self.db_manager.insert_radar_data(converted_data)
                if success:
                    logger.info(f"✅ [PROCESS] Dados enviados com sucesso para o Supabase!")
                else:
                    logger.error("❌ Falha ao enviar dados para o Supabase")
            except Exception as e:
                logger.error(f"❌ Erro ao enviar para o Supabase: {str(e)}")
                logger.error(traceback.format_exc())
        else:
            logger.warning("⚠️ Gerenciador do Supabase não disponível") 

def main():
    logger.info("🚀 Iniciando sistema de radar serial com Supabase...")
    
    try:
        # Verificar se as variáveis de ambiente do Supabase estão configuradas
        if not SUPABASE_CONFIG['url'] or not SUPABASE_CONFIG['anon_key'] or not SUPABASE_CONFIG['edge_function_url']:
            logger.error("❌ [MAIN] Variáveis de ambiente do Supabase não configuradas!")
            logger.error("❌ [MAIN] Configure SUPABASE_URL, SUPABASE_ANON_KEY e SUPABASE_EDGE_FUNCTION_URL")
            return
        
        # Inicializar o gerenciador do Supabase
        supabase_manager = SupabaseManager(
            SUPABASE_CONFIG['url'],
            SUPABASE_CONFIG['anon_key'],
            SUPABASE_CONFIG['edge_function_url']
        )
        logger.info("✅ SupabaseManager iniciado com sucesso!")
        
        # Teste de conectividade do Supabase
        try:
            test_result = supabase_manager.test_connection()
            
            if test_result:
                logger.info("✅ [MAIN] Teste do Supabase bem-sucedido!")
            else:
                logger.error("❌ [MAIN] Teste do Supabase falhou!")
                logger.error("❌ [MAIN] Verifique a URL da Edge Function e as credenciais")
                return
                
        except Exception as e:
            logger.error(f"❌ [MAIN] Erro no teste do Supabase: {str(e)}")
            logger.error(traceback.format_exc())
            return
        
        # Teste do parser com dados simulados
        test_radar_data = """-----Human Detected-----
Target 1:
x_point: 0.50
y_point: 1.20
dop_index: 6
move_speed: 15.20 cm/s
distance: 1.30
heart_rate: 75.0
breath_rate: 15.0"""
        
        parsed_data = parse_serial_data(test_radar_data)
        
        if parsed_data:
            logger.info("✅ [MAIN] Parser funcionando corretamente!")
        else:
            logger.error("❌ [MAIN] Parser falhou com dados simulados!")
        
        # Teste completo do processamento
        radar_manager_test = SerialRadarManager('/dev/ttyACM0', 115200)
        radar_manager_test.db_manager = supabase_manager
        
        try:
            radar_manager_test.process_radar_data(test_radar_data)
            logger.info("✅ [MAIN] Processamento completo funcionando!")
        except Exception as e:
            logger.error(f"❌ [MAIN] Erro no processamento completo: {str(e)}")
            logger.error(traceback.format_exc())
        
    except Exception as e:
        logger.error(f"❌ Erro ao criar instância do SupabaseManager: {e}")
        logger.error(traceback.format_exc())
        return
    
    # Definindo a porta serial diretamente
    port = '/dev/ttyACM0'
    baudrate = int(os.getenv("SERIAL_BAUDRATE", "115200"))
    
    radar_manager = SerialRadarManager(port, baudrate)
    
    try:
        logger.info(f"🔄 Iniciando SerialRadarManager...")
        
        success = radar_manager.start(supabase_manager)
        
        if not success:
            logger.error("❌ Falha ao iniciar o gerenciador de radar serial")
            return
        
        logger.info("="*50)
        logger.info("🚀 Sistema Radar Serial com Supabase iniciado com sucesso!")
        logger.info(f"📡 Porta serial: {radar_manager.port}")
        logger.info(f"📡 Baudrate: {radar_manager.baudrate}")
        logger.info(f"🔗 Supabase URL: {SUPABASE_CONFIG['url']}")
        logger.info(f"🔗 Edge Function: {SUPABASE_CONFIG['edge_function_url']}")
        logger.info("⚡ Pressione Ctrl+C para encerrar")
        logger.info("="*50)
        
        # Contador para mostrar status periódico
        loop_count = 0
        
        while True:
            time.sleep(1)
            loop_count += 1
            
            # Mostra status a cada 30 segundos
            if loop_count % 30 == 0:
                logger.info(f"📊 [STATUS] Sistema rodando há {loop_count} segundos")
                logger.info(f"📊 [STATUS] Mensagens: Recebidas={radar_manager.messages_received}, Processadas={radar_manager.messages_processed}, Falharam={radar_manager.messages_failed}")
                logger.info(f"📊 [STATUS] Conexão serial: {'✅ Ativa' if radar_manager.serial_connection and radar_manager.serial_connection.is_open else '❌ Inativa'}")
                logger.info(f"📊 [STATUS] Thread de recepção: {'✅ Ativa' if radar_manager.receive_thread and radar_manager.receive_thread.is_alive() else '❌ Inativa'}")
            
    except KeyboardInterrupt:
        logger.info("🔄 Encerrando por interrupção do usuário...")
        
    finally:
        radar_manager.stop()
        logger.info("✅ Sistema encerrado!")

if __name__ == "__main__":
    main() 
