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
import json
import signal
import sys

# Paths absolutos para SystemD
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CREDENTIALS_PATH = os.path.join(SCRIPT_DIR, 'credenciais2.json')
ENV_FILE_PATH = os.path.join(SCRIPT_DIR, '.env')

# Configuração básica de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s - %(message)s',  # Formato simplificado para SystemD
    handlers=[logging.StreamHandler()]     # SystemD captura automaticamente
)
logger = logging.getLogger('radar_serial_app')

# Configurando o nível de log para outros módulos
logging.getLogger('urllib3').setLevel(logging.WARNING)
logging.getLogger('gspread').setLevel(logging.WARNING)

# Carregar variáveis de ambiente do diretório correto
load_dotenv(ENV_FILE_PATH)

SERIAL_CONFIG = {
    'port': None,  # Será detectada automaticamente
    'baudrate': int(os.getenv('SERIAL_BAUDRATE', 115200))
}
RANGE_STEP = 2.5

class GoogleSheetsManager:
    def __init__(self, creds_path, spreadsheet_name, worksheet_name='Sheet1'):
        SCOPES = [
            'https://www.googleapis.com/auth/spreadsheets',
            'https://www.googleapis.com/auth/drive.readonly'
        ]
        
        try:
            self.creds = Credentials.from_service_account_file(creds_path, scopes=SCOPES)
        except Exception as e:
            logger.error(f"❌ Erro ao carregar credenciais: {str(e)}")
            raise
        
        try:
            self.gc = gspread.authorize(self.creds)
        except Exception as e:
            logger.error(f"❌ Erro na autorização: {str(e)}")
            raise
        
        try:
            # Permite abrir por URL, ID ou nome
            if isinstance(spreadsheet_name, str) and spreadsheet_name.startswith('http'):
                self.spreadsheet = self.gc.open_by_url(spreadsheet_name)
            elif isinstance(spreadsheet_name, str) and re.match(r'^[A-Za-z0-9_-]{40,}$', spreadsheet_name):
                self.spreadsheet = self.gc.open_by_key(spreadsheet_name)
            else:
                self.spreadsheet = self.gc.open(spreadsheet_name)
        except Exception as e:
            logger.error(f"❌ Erro ao abrir planilha: {str(e)}")
            raise
        
        try:
            self.worksheet = self.spreadsheet.worksheet(worksheet_name)
            logger.info(f"✅ Google Sheets conectado")
        except Exception as e:
            logger.error(f"❌ Erro ao acessar worksheet: {str(e)}")
            raise

    def insert_radar_data(self, data):
        try:
            row = [
                data.get('radar_id') or os.getenv('RADAR_ID', 'RADAR_1'),  # Radar_id (coluna A)
                data.get('session_id'),                                     # session_id (B)
                data.get('timestamp'),                                       # timestamp (C)
                data.get('x_point'),                                         # x_point (D)
                data.get('y_point'),                                         # y_point (E)
                data.get('move_speed'),                                      # move_speed (F)
                data.get('heart_rate'),                                      # heart_rate (G)
                data.get('breath_rate'),                                     # breath_rate (H)
                data.get('distance'),                                        # distance (I)
                data.get('section_id'),                                      # section_id (J)
                data.get('product_id'),                                      # product_id (K)
                data.get('satisfaction_score'),                              # satisfaction_score (L)
                data.get('satisfaction_class'),                              # satisfaction_class (M)
                data.get('is_engaged')                                       # is_engaged (N)
            ]
            
            # Verificar se há valores None ou problemáticos
            problematic_values = []
            for i, value in enumerate(row):
                if value is None:
                    problematic_values.append(f"índice {i}: None")
                elif isinstance(value, (int, float)) and (value != value):  # NaN check
                    problematic_values.append(f"índice {i}: NaN")
                elif isinstance(value, str) and len(value) > 1000:  # String muito longa
                    problematic_values.append(f"índice {i}: string muito longa ({len(value)} chars)")
            
            if problematic_values:
                logger.warning(f"⚠️ [GSHEETS] Valores problemáticos encontrados: {problematic_values}")
            
            self.worksheet.append_row(row)
            
            logger.info('✅ Dados enviados para o Google Sheets!')
            return True
            
        except Exception as e:
            logger.error(f'❌ [GSHEETS] Erro ao enviar dados para o Google Sheets: {str(e)}')
            logger.error(f'❌ [GSHEETS] Tipo do erro: {type(e)}')
            logger.error(f'❌ [GSHEETS] Dados que causaram o erro: {data}')
            
            # Verificações específicas para erros comuns
            error_msg = str(e).lower()
            if 'quota' in error_msg or 'rate' in error_msg:
                logger.error(f'❌ [GSHEETS] Erro de limite de taxa da API! Aguarde antes de tentar novamente.')
                logger.error(f'❌ [GSHEETS] Considere adicionar delays entre as requisições.')
            elif 'permission' in error_msg or 'forbidden' in error_msg:
                logger.error(f'❌ [GSHEETS] Erro de permissão! Verifique as credenciais e permissões da planilha.')
            elif 'not found' in error_msg:
                logger.error(f'❌ [GSHEETS] Planilha ou worksheet não encontrada! Verifique o nome da planilha.')
            elif 'authentication' in error_msg or 'auth' in error_msg:
                logger.error(f'❌ [GSHEETS] Erro de autenticação! Verifique o arquivo de credenciais.')
            else:
                logger.error(f'❌ [GSHEETS] Erro desconhecido da API do Google Sheets.')
            
            logger.error(traceback.format_exc())
            return False

def parse_serial_data(raw_data):
    try:
        # Suporte para múltiplos formatos de dados do Arduino
        
        # FORMATO 1: Formato atual do radar (Human Detected + Target)
        # -----Human Detected-----
        # breath_rate: 30.00
        # heart_rate: 82.00
        # x_position: -0.15
        # y_position: 0.38
        # distance: -0.00
        # Target 1:
        #   x_point: -0.15
        #   y_point: 0.38
        #   dop_index: 0
        #   cluster_index: 0
        #   move_speed: 0.00 cm/s
        has_human_detected = '-----Human Detected-----' in raw_data
        has_target_1 = 'Target 1:' in raw_data
        
        if has_human_detected and has_target_1:
            logger.debug("📡 [PARSER] Detectado formato atual do radar (Human Detected + Target)")
            
            # Padrões regex para todos os campos solicitados
            x_position_pattern = r'x_position\s*:\s*([-+]?\d*\.?\d+)'
            y_position_pattern = r'y_position\s*:\s*([-+]?\d*\.?\d+)'
            x_point_pattern = r'x_point\s*:\s*([-+]?\d*\.?\d+)'
            y_point_pattern = r'y_point\s*:\s*([-+]?\d*\.?\d+)'
            breath_rate_pattern = r'breath_rate\s*:\s*([-+]?\d*\.?\d+)'
            heart_rate_pattern = r'heart_rate\s*:\s*([-+]?\d*\.?\d+)'
            distance_pattern = r'distance\s*:\s*([-+]?\d*\.?\d+)'
            move_speed_pattern = r'move_speed\s*:\s*([-+]?\d*\.?\d+)\s*cm/s'
            dop_index_pattern = r'dop_index\s*:\s*([-+]?\d+)'
            cluster_index_pattern = r'cluster_index\s*:\s*(\d+)'
            
            # Busca por todos os campos
            x_position_match = re.search(x_position_pattern, raw_data, re.IGNORECASE)
            y_position_match = re.search(y_position_pattern, raw_data, re.IGNORECASE)
            x_point_match = re.search(x_point_pattern, raw_data, re.IGNORECASE)
            y_point_match = re.search(y_point_pattern, raw_data, re.IGNORECASE)
            breath_rate_match = re.search(breath_rate_pattern, raw_data, re.IGNORECASE)
            heart_rate_match = re.search(heart_rate_pattern, raw_data, re.IGNORECASE)
            distance_match = re.search(distance_pattern, raw_data, re.IGNORECASE)
            move_speed_match = re.search(move_speed_pattern, raw_data, re.IGNORECASE)
            dop_index_match = re.search(dop_index_pattern, raw_data, re.IGNORECASE)
            cluster_index_match = re.search(cluster_index_pattern, raw_data, re.IGNORECASE)
            
            # Prioriza x_point/y_point se disponíveis, senão usa x_position/y_position
            x_coord = None
            y_coord = None
            
            if x_point_match and y_point_match:
                x_coord = float(x_point_match.group(1))
                y_coord = float(y_point_match.group(1))
                logger.debug(f"📡 [PARSER] Usando coordenadas do Target: x={x_coord}, y={y_coord}")
            elif x_position_match and y_position_match:
                x_coord = float(x_position_match.group(1))
                y_coord = float(y_position_match.group(1))
                logger.debug(f"📡 [PARSER] Usando coordenadas de posição: x={x_coord}, y={y_coord}")
            
            if x_coord is not None and y_coord is not None:
                # Extrai velocidade (move_speed em cm/s)
                move_speed = 0.0
                if move_speed_match:
                    move_speed = float(move_speed_match.group(1))  # cm/s
                    logger.debug(f"📡 [PARSER] Velocidade detectada: {move_speed} cm/s")
                
                # Extrai dados vitais
                breath_rate = 15.0  # Valor padrão
                if breath_rate_match:
                    breath_rate = float(breath_rate_match.group(1))
                    logger.debug(f"📡 [PARSER] Taxa de respiração: {breath_rate}")
                
                heart_rate = 75.0  # Valor padrão
                if heart_rate_match:
                    heart_rate = float(heart_rate_match.group(1))
                    logger.debug(f"📡 [PARSER] Frequência cardíaca: {heart_rate}")
                
                # Extrai distância
                distance = None
                if distance_match:
                    distance = float(distance_match.group(1))
                    logger.debug(f"📡 [PARSER] Distância: {distance}")
                
                # Calcula distância se não fornecida ou se for inválida
                if distance is None or distance <= 0:
                    distance = math.sqrt(x_coord**2 + y_coord**2)
                    logger.debug(f"📡 [PARSER] Distância calculada: {distance}")
                
                # Extrai índices
                dop_index = int(dop_index_match.group(1)) if dop_index_match else 0
                cluster_index = int(cluster_index_match.group(1)) if cluster_index_match else 0
                
                data = {
                    'x_point': x_coord,
                    'y_point': y_coord,
                    'breath_rate': breath_rate,
                    'heart_rate': heart_rate,
                    'distance': distance,
                    'move_speed': move_speed,
                    'dop_index': dop_index,
                    'cluster_index': cluster_index,
                    'total_phase': 0.0,  # Não disponível no formato atual
                    'breath_phase': 0.0,  # Não disponível no formato atual
                    'heart_phase': 0.0    # Não disponível no formato atual
                }
                
                logger.info(f"✅ [PARSER] Dados parseados: X={x_coord:.2f}m, Y={y_coord:.2f}m, ❤️{heart_rate:.0f}, 🫁{breath_rate:.0f}, 🏃{move_speed:.2f}m/s")
                return data
        
        # FORMATO 2: Formato simples (send_formatted_data)
        # breath_rate: 15.00
        # heart_rate: 75.00  
        # x_position: 0.50
        # y_position: 1.20
        if 'breath_rate:' in raw_data and 'x_position:' in raw_data:
            logger.debug("📡 [PARSER] Detectado formato simples do Arduino")
            
            breath_rate_match = re.search(r'breath_rate\s*:\s*([-+]?\d*\.?\d+)', raw_data, re.IGNORECASE)
            heart_rate_match = re.search(r'heart_rate\s*:\s*([-+]?\d*\.?\d+)', raw_data, re.IGNORECASE)
            x_position_match = re.search(r'x_position\s*:\s*([-+]?\d*\.?\d+)', raw_data, re.IGNORECASE)
            y_position_match = re.search(r'y_position\s*:\s*([-+]?\d*\.?\d+)', raw_data, re.IGNORECASE)
            
            if x_position_match and y_position_match:
                data = {
                    'x_point': float(x_position_match.group(1)),
                    'y_point': float(y_position_match.group(1)),
                    'breath_rate': float(breath_rate_match.group(1)) if breath_rate_match else 15.0,
                    'heart_rate': float(heart_rate_match.group(1)) if heart_rate_match else 75.0,
                    'distance': math.sqrt(float(x_position_match.group(1))**2 + float(y_position_match.group(1))**2),
                    'move_speed': 0.0,
                    'dop_index': 0,
                    'cluster_index': 0,
                    'total_phase': 0.0,
                    'breath_phase': 0.0,
                    'heart_phase': 0.0
                }
                return data
        
        # FORMATO 3: Mensagens do sistema (não processa dados, só registra)
        if any(msg in raw_data for msg in ['HEARTBEAT:', 'DEEP SLEEP', 'Acordou', 'Sistema ativo']):
            logger.debug(f"📡 [PARSER] Mensagem do sistema: {raw_data.strip()}")
            return None
            
        # Se nenhum formato foi reconhecido
        logger.warning(f"⚠️ [PARSER] Formato não reconhecido: {raw_data[:100]}...")
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

# Remover importação da EmotionalStateAnalyzer e campos emocionais
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
        # self.emotional_analyzer = EmotionalStateAnalyzer()  # Removido
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
        """Detecta automaticamente a porta serial do Arduino/ESP32"""
        try:
            import serial.tools.list_ports
            
            logger.info("🔍 Buscando portas seriais disponíveis...")
            ports = list(serial.tools.list_ports.comports())
            
            if not ports:
                logger.error("❌ Nenhuma porta serial encontrada!")
                return None
            
            logger.info(f"📋 {len(ports)} porta(s) encontrada(s):")
            
            # Lista todas as portas para debug
            for i, port in enumerate(ports):
                logger.info(f"   {i+1}. {port.device}")
                logger.info(f"      Descrição: {port.description}")
                if hasattr(port, 'manufacturer') and port.manufacturer:
                    logger.info(f"      Fabricante: {port.manufacturer}")
            
            # PRIORIDADE 1: Busca ESP32/Espressif primeiro
            for port in ports:
                desc = str(port.description).lower()
                manuf = str(getattr(port, 'manufacturer', '')).lower()
                
                if 'espressif' in manuf or 'esp32' in desc or 'esp-32' in desc:
                    logger.info(f"✅ ESP32 detectado: {port.device}")
                    return port.device
            
            # PRIORIDADE 2: Busca Arduino
            for port in ports:
                desc = str(port.description).lower()
                if 'arduino' in desc or 'uno' in desc or 'nano' in desc:
                    logger.info(f"✅ Arduino detectado: {port.device}")
                    return port.device
            
            # PRIORIDADE 3: Busca chips USB-Serial comuns
            for port in ports:
                desc = str(port.description).lower()
                device = str(port.device).lower()
                
                # Chips conhecidos
                if any(chip in desc for chip in ['cp210', 'ch340', 'ft232', 'pl2303']):
                    logger.info(f"✅ Chip USB-Serial detectado: {port.device}")
                    return port.device
                
                # Padrões de nome no macOS/Linux
                if any(pattern in device for pattern in ['usbmodem', 'ttyusb', 'ttyacm']):
                    logger.info(f"✅ Porta USB detectada: {port.device}")
                    return port.device
            
            # ÚLTIMO RECURSO: Primeira porta que não seja Bluetooth
            for port in ports:
                device_lower = str(port.device).lower()
                desc_lower = str(port.description).lower()
                
                # Evita portas Bluetooth e debug console
                if not any(skip in device_lower or skip in desc_lower for skip in 
                          ['bluetooth', 'debug-console', 'incoming-port']):
                    logger.warning(f"⚠️ Usando primeira porta válida: {port.device}")
                    return port.device
            
            # Se tudo falhar, usa a primeira
            logger.warning(f"⚠️ Usando primeira porta disponível: {ports[0].device}")
            return ports[0].device
            
        except Exception as e:
            logger.error(f"❌ Erro na detecção de porta: {str(e)}")
            return None
    
    def _test_port_communication(self, port_device):
        """Testa se uma porta pode ser aberta e comunicar"""
        try:
            with serial.Serial(port_device, self.baudrate, timeout=1) as test_serial:
                # Tenta ler alguns bytes para ver se há atividade
                test_serial.read(10)
                return True
        except Exception:
            return False

    def connect(self):
        # Sempre detecta automaticamente a porta serial
        if not self.port:
            logger.info("🔍 Detectando porta serial automaticamente...")
            detected_port = self.find_serial_port()
            if detected_port:
                self.port = detected_port
                logger.info(f"✅ Porta serial detectada: {self.port}")
            else:
                logger.error("❌ Nenhuma porta serial disponível para conexão!")
                return False
        else:
            # Verifica se a porta atual ainda existe
            if not os.path.exists(self.port):
                logger.warning(f"⚠️ Porta {self.port} desconectada. Detectando nova porta...")
                detected_port = self.find_serial_port()
                if detected_port:
                    self.port = detected_port
                    logger.info(f"✅ Nova porta detectada: {self.port}")
                else:
                    logger.error("❌ Nenhuma porta serial disponível!")
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
        """Inicia o sistema de radar para SystemD"""
        self.db_manager = db_manager
        self.is_running = True
        
        try:
            # Conecta ao radar
            if not self.connect():
                logger.error("❌ Falha ao conectar com o radar")
                return False
            
            # Configuração inicial do sensor
            self.configure_sensor_continuous_mode()
            time.sleep(3)
            
            # Inicia thread de recepção (única thread necessária)
            self.receive_thread = threading.Thread(target=self.receive_data_loop, daemon=True)
            self.receive_thread.start()
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Erro ao iniciar sistema: {str(e)}")
            return False



    def stop(self):
        """Para o sistema de radar para SystemD"""
        self.is_running = False
        
        # Para thread de recepção
        if hasattr(self, 'receive_thread') and self.receive_thread and self.receive_thread.is_alive():
            self.receive_thread.join(timeout=2)
        
        # Fecha conexão serial
        if self.serial_connection and self.serial_connection.is_open:
            self.serial_connection.close()
        
        logger.info("✅ Sistema de radar parado!")

    def hardware_reset_arduino(self):
        """
        Reinicia o Arduino/ESP32 via pulso nas linhas DTR/RTS da porta serial.
        Compatível com o novo código Arduino MR60BHA2.
        """
        try:
            logger.warning("[ARDUINO RESET] Iniciando reset via DTR/RTS na porta serial...")
            # Fecha a conexão principal se estiver aberta
            was_open = False
            if self.serial_connection and self.serial_connection.is_open:
                self.serial_connection.close()
                was_open = True
                
            # Aguarda um pouco antes de fazer o reset
            time.sleep(1)
            
            # Abre uma conexão temporária só para reset
            with serial.Serial(self.port, self.baudrate, timeout=1) as ser:
                # Sequência de reset compatível com ESP32 e Arduino
                ser.setDTR(False)
                ser.setRTS(True)
                time.sleep(0.1)
                ser.setDTR(True)
                ser.setRTS(False)
                time.sleep(0.1)
                
                # Reset adicional específico para ESP32
                ser.setDTR(False)
                time.sleep(0.1)
                ser.setDTR(True)
                time.sleep(0.5)
                
            logger.info("[ARDUINO RESET] Pulso de reset enviado com sucesso!")
            
            # Aguarda Arduino reinicializar (baseado no código Arduino)
            logger.info("[ARDUINO RESET] Aguardando Arduino reinicializar...")
            time.sleep(3)  # Arduino precisa de tempo para inicializar
            
            # Reabre a conexão principal se estava aberta
            if was_open:
                self.connect()
            return True
        except Exception as e:
            logger.error(f"[ARDUINO RESET] Falha ao resetar Arduino: {e}")
            logger.error(traceback.format_exc())
            return False

    def receive_data_loop(self):
        buffer = ""
        last_data_time = time.time()
        if not hasattr(self, 'last_valid_data_time'):
            self.last_valid_data_time = time.time()
        self.RESET_TIMEOUT = 600  # 10 minutos (tolerante com deep sleep do Arduino)
        # Loop de recepção de dados iniciado

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
                        
                        # Log simplificado para SystemD
                        if line.strip():
                            # Dados do radar - prioridade máxima
                            if any(key in line for key in ['breath_rate', 'heart_rate', 'x_position', 'y_position', 'Human Detected', 'Target']):
                                logger.debug(f"🎯 Dados: {line.strip()}")
                            # Erros críticos - importante
                            elif any(critical in line for critical in ['CRÍTICO', 'FALHOU', 'ERROR', '❌']):
                                logger.warning(f"⚠️ {line.strip()}")
                            # Outros - silencioso
                            else:
                                logger.debug(f"Debug: {line.strip()}")
                        
                        # === DETECÇÃO DE DADOS DO ARDUINO (PRIORIDADE MÁXIMA) ===
                        
                        # FORMATO 1: JSON do Arduino (formato atual)
                        # {"radar_id":"RADAR_1","timestamp_ms":12345,"person_count":1,"active_people":[{"x_pos":0.5,"y_pos":1.2,"distance_raw":1.3,"confidence":85}]}
                        if line.strip().startswith('{') and line.strip().endswith('}'):
                            try:
                                import json
                                json_data = json.loads(line.strip())
                                if 'active_people' in json_data and json_data.get('person_count', 0) > 0:
                                    logger.debug(f"🎯 JSON detectado: {line.strip()}")
                                    self.process_radar_data(line.strip())
                                    self.last_valid_data_time = time.time()
                                    continue
                            except (json.JSONDecodeError, ImportError):
                                pass  # Não é JSON válido, continua para outros formatos
                        
                        # Formato simples: linhas individuais de dados
                        if any(key in line for key in ['breath_rate:', 'heart_rate:', 'x_position:', 'y_position:']):
                            if not coletando_bloco:
                                coletando_bloco = True
                                bloco_buffer = ""
                            bloco_buffer += line + "\n"
                            # Se temos todos os 4 campos básicos, processa imediatamente
                            if all(key in bloco_buffer for key in ['breath_rate:', 'heart_rate:', 'x_position:', 'y_position:']):
                                self.process_radar_data(bloco_buffer)
                                coletando_bloco = False
                                bloco_buffer = ""
                                self.last_valid_data_time = time.time()
                            continue
                        
                        # Formato completo: começa with Human Detected
                        if '-----Human Detected-----' in line:
                            coletando_bloco = True
                            bloco_buffer = line + "\n"
                            continue
                        elif coletando_bloco:
                            if line.strip() == "":
                                # Linha em branco: fim do bloco!
                                self.process_radar_data(bloco_buffer)
                                coletando_bloco = False
                                bloco_buffer = ""
                                self.last_valid_data_time = time.time()  # Atualiza quando processa dados
                            else:
                                bloco_buffer += line + "\n"
                            continue
                        
                        # === COMANDOS E STATUS DO ARDUINO ===
                        
                        # Detecta heartbeat do ESP32/Arduino
                        if 'HEARTBEAT: Sistema ativo' in line or 'HEARTBEAT:' in line:
                            last_data_time = time.time()  # Atualiza timestamp de dados
                            self.last_valid_data_time = time.time()
                            continue
                        
                        # Detecta deep sleep horário (Arduino)
                        if '=== DEEP SLEEP HORÁRIO ===' in line or 'DEEP SLEEP HORÁRIO' in line:
                            logger.info("😴 Arduino em deep sleep (1 minuto)")
                            coletando_bloco = False
                            bloco_buffer = ""
                            continue
                        
                        # Detecta teste de deep sleep (Arduino)
                        if '=== TESTE DE DEEP SLEEP ===' in line:
                            logger.info("🧪 [SERIAL] Arduino executando teste de deep sleep")
                            coletando_bloco = False
                            bloco_buffer = ""
                            continue
                            
                        # Detecta entrada em deep sleep
                        if 'Entrando em deep sleep' in line:
                            logger.info("😴 [SERIAL] Arduino entrando em deep sleep")
                            continue
                        
                        # Detecta saída do deep sleep
                        if 'Acordou do deep sleep' in line or 'Voltando ao modo de operação normal' in line:
                            logger.info("🌅 [SERIAL] Arduino saiu do deep sleep - voltando ao normal")
                            continue
                        
                        # Detecta reset do sistema
                        if '=== RESETANDO SISTEMA COMPLETO ===' in line:
                            logger.info("🔄 [SERIAL] ESP32 executando reset completo do sistema")
                            coletando_bloco = False
                            bloco_buffer = ""
                            continue
                        
                        # Detecta reinicialização do sensor
                        if '=== REINICIALIZANDO SENSOR ===' in line or 'Sensor MR60BHA2 reinicializado' in line:
                            logger.info("🔧 [SERIAL] ESP32 reinicializando sensor MR60BHA2")
                            continue
                        
                        # Detecta diagnósticos do sistema (Arduino)
                        if '=== DIAGNÓSTICO COMPLETO DO SISTEMA ===' in line or 'DIAGNÓSTICO' in line:
                            logger.info("🔍 [SERIAL] Arduino executando diagnóstico completo")
                            continue
                        
                        # Detecta problemas de memória (Arduino)
                        if 'ALERTA: Memória baixa!' in line or 'Fragmentação crítica detectada' in line:
                            logger.warning("⚠️ [SERIAL] Arduino detectou problemas de memória")
                            continue
                            
                        # Detecta verificações específicas do Arduino
                        if any(check in line for check in ['=== DEBUG', '=== VERIFICAÇÃO', '=== TESTE']):
                            logger.debug(f"🔧 [SERIAL] Arduino: {line.strip()}")
                            continue
                        
                        # Detecta problemas de comunicação
                        if 'ALERTA: Conexão instável detectada!' in line:
                            logger.warning("⚠️ [SERIAL] ESP32 detectou problemas de comunicação")
                            continue
                        
                        # Detecta ativação do sensor
                        if 'Sensor ativado e funcionando!' in line:
                            logger.info("✅ [SERIAL] Sensor MR60BHA2 ativado com sucesso")
                            continue
                        
                        # Detecta modo inativo do sensor
                        if 'Sensor em modo inativo' in line:
                            logger.warning("😴 [SERIAL] Sensor MR60BHA2 em modo inativo - aguardando ativação")
                            continue
                        
                        # Ignora mensagens de debug verboso do Arduino
                        if any(ignore in line for ignore in [
                            'DADOS SIMULADOS', 'Método robusto falhou', 'usando dados simulados', 
                            'TENTATIVA ROBUSTA', 'Todas as tentativas falharam', 'Tentativa', 'Falha na',
                            'CRÍTICO: Posição E dados vitais falharam', 'Problema sério de comunicação',
                            'DEBUG DADOS VITAIS', 'FIM DEBUG VITAIS', 'DEBUG POSIÇÃO'
                        ]):
                            continue
                        
                        # Detecta se ESP32 entrou em modo download
                        if 'waiting for download' in line or 'DOWNLOAD(' in line:
                            logger.warning("⚠️ [SERIAL] ESP32 entrou em modo download! Aguardando reinicialização...")
                            coletando_bloco = False
                            bloco_buffer = ""
                            time.sleep(5)  # Aguarda 5 segundos para ESP32 reiniciar
                            continue
                        
                        # Detecta estatísticas do sistema
                        if 'Loop ativo - Total:' in line:
                            logger.debug(f"📊 [SERIAL] {line.strip()}")
                            continue
                        
                        # Detecta status de deep sleep
                        if 'Próximo deep sleep em:' in line:
                            logger.debug(f"⏰ [SERIAL] {line.strip()}")
                            continue
                        


                current_time = time.time()
                if current_time - self.last_valid_data_time > self.RESET_TIMEOUT:
                    logger.warning("⚠️ Nenhum dado ou heartbeat recebido por mais de 10 minutos. Executando reset automático do Arduino via DTR/RTS...")
                    self.hardware_reset_arduino()
                    self.last_valid_data_time = current_time

                # Limpeza periódica de memória - REMOVIDO para SystemD
                
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
                        
                        # Tenta reconectar
                        time.sleep(2)
                        try:
                            self.connect()
                        except Exception as reconnect_error:
                            logger.error(f"❌ [SERIAL] Falha na reconexão: {reconnect_error}")
                            time.sleep(5)  # Aguarda mais tempo antes da próxima tentativa
                else:
                    logger.error(f"❌ [SERIAL] Erro desconhecido: {e}")
                    time.sleep(1)
            except Exception as e:
                logger.error(f"❌ [SERIAL] Erro geral no loop: {str(e)}")
                logger.error(traceback.format_exc())
                time.sleep(1)

    def reset_radar(self):
        """Executa um reset no radar - adaptado para o novo código Arduino"""
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
            
            # === NOVOS COMANDOS DE RESET DO ARDUINO ===
            
            # 1. Tenta comando Tiny Frame (protocolo do MR60BHA2)
            logger.info("[RESET] Enviando comando de reset via Tiny Frame...")
            reset_frame = bytes([0x02, 0x01, 0x01, 0x00, 0x04])  # Frame de reset
            self.serial_connection.write(reset_frame)
            time.sleep(1)
            
            # 2. Tenta comando ASCII
            logger.info("[RESET] Enviando comando de reset ASCII...")
            self.serial_connection.write(b'RESET\n')
            time.sleep(1)
            self.serial_connection.write(b'RST\n')
            time.sleep(1)
            
            # 3. Aguarda resposta do radar
            logger.info("[RESET] Aguardando resposta do radar...")
            time.sleep(3)  # Aguarda radar processar comandos
            
            # 4. Verifica se há resposta
            if self.serial_connection.in_waiting > 0:
                response = self.serial_connection.read(self.serial_connection.in_waiting)
                logger.info(f"[RESET] Resposta recebida: {response}")
            
            logger.info("✅ [RESET] Reset do radar concluído com sucesso!")
            return True
            
        except Exception as e:
            logger.error(f"❌ [RESET] Erro ao resetar o radar: {str(e)}")
            logger.error(traceback.format_exc())
            return False



    def configure_sensor_continuous_mode(self):
        """Configura sensor para modo contínuo - Adaptado para novo Arduino"""
        try:
            if self.serial_connection and self.serial_connection.is_open:
                logger.info("[CONFIG] Configurando sensor para modo contínuo (Arduino MR60BHA2)...")
                
                # === COMANDOS ESPECÍFICOS PARA O NOVO ARDUINO ===
                
                # Comandos para modo contínuo via Tiny Frame (baseado no código Arduino)
                continuous_mode_frame = bytes([0x02, 0x01, 0x02, 0x01, 0x06])
                self.serial_connection.write(continuous_mode_frame)
                time.sleep(0.5)
                
                # Comando para desabilitar sleep
                sleep_disable_frame = bytes([0x02, 0x01, 0x03, 0x00, 0x06])
                self.serial_connection.write(sleep_disable_frame)
                time.sleep(0.5)
                
                # Comando para modo sempre ativo
                always_on_frame = bytes([0x02, 0x01, 0x04, 0x01, 0x08])
                self.serial_connection.write(always_on_frame)
                time.sleep(0.5)
                
                # === COMANDOS ASCII COMPATÍVEIS COM O ARDUINO ===
                ascii_commands = [
                    "CONTINUOUS_MODE=1",
                    "SLEEP_MODE=0", 
                    "ALWAYS_ON=1",
                    "TIMEOUT=0",
                    "CONTINUOUS_DETECTION=1",
                    "POSITION_MODE=1",  # Novo: ativa modo de posição
                    "TARGET_TRACKING=1"  # Novo: ativa rastreamento de alvos
                ]
                
                for cmd in ascii_commands:
                    self.serial_connection.write(f"{cmd}\n".encode())
                    time.sleep(0.2)
                
                logger.info("✅ [CONFIG] Sensor configurado para modo contínuo compatível com Arduino")
                return True
                
        except Exception as e:
            logger.error(f"❌ [CONFIG] Erro ao configurar sensor: {str(e)}")
            return False


    
    def _show_satisfaction_summary(self):
        """Mostra resumo periódico das estatísticas de satisfação"""
        try:
            if not self.satisfaction_history:
                return
                
            current_time = time.time()
            if current_time - self.last_satisfaction_summary < self.SATISFACTION_SUMMARY_INTERVAL:
                return
                
            # Filtra dados dos últimos 5 minutos
            recent_data = [entry for entry in self.satisfaction_history 
                          if current_time - entry['timestamp'] < 300]  # 5 minutos
            
            if not recent_data:
                return
                
            # Calcula estatísticas
            scores = [entry['score'] for entry in recent_data]
            classes = [entry['class'] for entry in recent_data]
            
            avg_score = sum(scores) / len(scores)
            
            # Conta classificações
            class_count = {}
            for cls in classes:
                class_count[cls] = class_count.get(cls, 0) + 1
                
            # Encontra classificação dominante
            dominant_class = max(class_count, key=class_count.get)
            
            logger.info("📈" * 15)
            logger.info("📊 RESUMO DE SATISFAÇÃO (Últimos 5 min)")
            logger.info("📈" * 15)
            logger.info(f"📊 Total de medições: {len(recent_data)}")
            logger.info(f"🎯 Score médio: {avg_score:.1f}/100")
            logger.info(f"🏆 Classificação dominante: {dominant_class}")
            logger.info("-" * 40)
            for cls, count in class_count.items():
                percentage = (count / len(recent_data)) * 100
                logger.info(f"   {cls}: {count} ({percentage:.1f}%)")
            logger.info("📈" * 15)
            
            self.last_satisfaction_summary = current_time
            
        except Exception as e:
            logger.error(f"[SATISFACTION] Erro no resumo: {str(e)}")

    def _check_engagement(self, section_id, distance, move_speed):
        # Engajamento: basta a última leitura ser válida
        if section_id is not None and distance <= self.ENGAGEMENT_DISTANCE and move_speed <= self.ENGAGEMENT_SPEED:
            return True
        return False

    def process_radar_data(self, raw_data):
        # Usa o parser atualizado que suporta múltiplos formatos incluindo JSON
        data = parse_serial_data(raw_data)
        
        if data is None:
            logger.warning(f"❌ [PROCESS] Parser retornou None para: {raw_data[:200]}...")
            return
            
        # Marca como dados reais (sem simulação automática)
        data['is_simulated'] = False
        
        self.messages_processed += 1
        
        # Log conciso para SystemD
        logger.info(f"✅ Cliente: x={data.get('x_point', 0):.1f}m y={data.get('y_point', 0):.1f}m ❤️{data.get('heart_rate', 0):.0f} 🫁{data.get('breath_rate', 0):.0f}")
        
        x = data.get('x_point', 0)
        y = data.get('y_point', 0)
        dop_index_val = data.get('dop_index', None)
        move_speed = data.get('move_speed', None)
        if move_speed is None:
            move_speed = abs(dop_index_val) if dop_index_val is not None else 0.0  # cm/s
        
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
        
        dop_index = data.get('dop_index', None)
        if move_speed is None:
            move_speed = abs(dop_index) if dop_index is not None else 0.0
        
        converted_data = {
            'radar_id': os.getenv('RADAR_ID', 'RADAR_1'),
            'session_id': self.current_session_id,
            'x_point': data.get('x_point', 0),
            'y_point': data.get('y_point', 0),
            'move_speed': move_speed,
            'distance': distance,
            'dop_index': dop_index,
            'heart_rate': heart_rate,
            'breath_rate': breath_rate,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'is_simulated': data.get('is_simulated', False)
        }
        
        section = shelf_manager.get_section_at_position(
            converted_data['x_point'],
            converted_data['y_point'],
            self.db_manager
        )
        
        if section:
            converted_data['section_id'] = section['section_id']
            converted_data['product_id'] = section['product_id']
            
            # Calcula satisfação apenas se tiver dados vitais
            if heart_rate is not None and breath_rate is not None:
                satisfaction_result = self.analytics_manager.calculate_satisfaction_score(
                    move_speed, heart_rate, breath_rate, distance
                )
                satisfaction_score, satisfaction_class = satisfaction_result
                converted_data['satisfaction_score'] = satisfaction_score
                converted_data['satisfaction_class'] = satisfaction_class
                
                # Log simplificado para SystemD
                emoji_map = {
                    "MUITO_POSITIVA": "😍",
                    "POSITIVA": "😊", 
                    "NEUTRA": "😐",
                    "NEGATIVA": "😞",
                    "MUITO_NEGATIVA": "😡"
                }
                emoji = emoji_map.get(satisfaction_class, "❓")
                
                logger.info(f"📊 Análise: {emoji} {satisfaction_class} ({satisfaction_score:.0f}/100) | Dist: {distance:.1f}m | Vel: {move_speed:.0f}cm/s")
                
                # Engajamento
                is_engaged = self._check_engagement(section['section_id'] if section else None, distance, move_speed)
                engagement_text = "🔥" if is_engaged else "💤"
                logger.info(f"Engajamento: {engagement_text}")
                
                if section:
                    logger.info(f"🏪 {section.get('section_name', 'N/A')} | 📦 {section.get('product_id', 'N/A')}")
            else:
                converted_data['satisfaction_score'] = None
                converted_data['satisfaction_class'] = None
                logger.info("⚠️ Dados vitais insuficientes para análise de satisfação")
            
            # Verifica engajamento
            converted_data['is_engaged'] = self._check_engagement(
                section['section_id'], distance, move_speed
            )
        else:
            converted_data['section_id'] = None
            converted_data['product_id'] = None
            converted_data['satisfaction_score'] = None
            converted_data['satisfaction_class'] = None
            converted_data['is_engaged'] = False
        
        # Envia para Google Sheets
        try:
            self.db_manager.insert_radar_data(converted_data)
            logger.debug(f"✅ Dados enviados para Google Sheets")
                
        except Exception as e:
            logger.error(f"❌ Erro ao enviar dados: {str(e)}")

def main():
    # Signal handler para graceful shutdown com SystemD
    def signal_handler(signum, frame):
        logger.info("🔄 Shutdown graceful solicitado pelo SystemD")
        if 'radar_manager' in locals():
            radar_manager.stop()
        sys.exit(0)
    
    # Registrar handlers para SystemD (SIGTERM) e Ctrl+C (SIGINT)
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    
    logger.info("🚀 Iniciando sistema de radar para SystemD...")
    
    try:
        # Usar path absoluto otimizado
        gsheets_manager = GoogleSheetsManager(CREDENTIALS_PATH, 'https://docs.google.com/spreadsheets/d/1MaXRVAe1iD2TH45e1BCObthJXUe_A33VJMKLO_roF74/edit?usp=sharing')
        logger.info("✅ Google Sheets conectado")
        
    except Exception as e:
        logger.error(f"❌ Erro ao conectar Google Sheets: {e}")
        sys.exit(1)  # SystemD reinicia automaticamente
    
    # Detecção automática de porta
    port = None
    baudrate = int(os.getenv("SERIAL_BAUDRATE", "115200"))
    
    radar_manager = SerialRadarManager(port, baudrate)
    
    try:
        success = radar_manager.start(gsheets_manager)
        
        if not success:
            logger.error("❌ Falha ao iniciar o radar")
            sys.exit(1)  # SystemD reinicia automaticamente
        
        logger.info(f"✅ Sistema iniciado - Porta: {radar_manager.port}")
        
        # Loop principal simplificado para SystemD
        while True:
            time.sleep(1)
            
            # Status a cada 60 segundos (menos verboso)
            if time.time() % 60 < 1:
                logger.info(f"📊 Sistema ativo - Porta: {radar_manager.port}")
            
    except Exception as e:
        logger.error(f"❌ Erro crítico: {e}")
        sys.exit(1)  # SystemD reinicia automaticamente
        
    finally:
        radar_manager.stop()
        logger.info("✅ Sistema encerrado!")

if __name__ == "__main__":
    main() 
