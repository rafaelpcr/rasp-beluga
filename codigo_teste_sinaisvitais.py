import mysql.connector
from datetime import datetime, timedelta
import logging
import json
import os
from dotenv import load_dotenv
import traceback
import time
import numpy as np
import uuid
import serial
import threading
import re
import math

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

# Carregar variáveis de ambiente
load_dotenv()

# Configurações do banco de dados
DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'localhost'),
    'user': os.getenv('DB_USER', 'root'),
    'password': os.getenv('DB_PASSWORD', ''),
    'database': os.getenv('DB_NAME', 'radar_serial'),
    'port': int(os.getenv('DB_PORT', 3306))
}

# Configurações da porta serial
SERIAL_CONFIG = {
    'port': os.getenv('SERIAL_PORT', '/dev/ttyUSB0'),
    'baudrate': int(os.getenv('SERIAL_BAUDRATE', 115200))
}

# Constante para conversão do índice Doppler para velocidade
RANGE_STEP = 2.5  # Valor do RANGE_STEP do código ESP32/Arduino

def parse_serial_data(raw_data):
    """Analisa os dados brutos da porta serial para extrair informações do radar mmWave"""
    try:
        # Padrões atualizados para corresponder exatamente ao formato do Arduino
        x_pattern = r'x_point:\s*([-]?\d+\.\d+)'
        y_pattern = r'y_point:\s*([-]?\d+\.\d+)'
        dop_pattern = r'dop_index:\s*([-]?\d+)'  # Modificado para aceitar valores negativos
        cluster_pattern = r'cluster_index:\s*(\d+)'
        speed_pattern = r'move_speed:\s*([-]?\d+\.\d+)\s*cm/s'
        total_phase_pattern = r'total_phase:\s*([-]?\d+\.\d+)'
        breath_phase_pattern = r'breath_phase:\s*([-]?\d+\.\d+)'
        heart_phase_pattern = r'heart_phase:\s*([-]?\d+\.\d+)'
        breath_rate_pattern = r'breath_rate:\s*([-]?\d+\.\d+)'
        heart_rate_pattern = r'heart_rate:\s*([-]?\d+\.\d+)'
        distance_pattern = r'distance:\s*([-]?\d+\.\d+)'
        
        # Verificar se temos uma detecção humana
        if '-----Human Detected-----' not in raw_data:
            return None
            
        # Verificar se temos informações do alvo
        if 'Target 1:' not in raw_data:
            return None
            
        # Extrair valores usando expressões regulares
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
        
        # Extrair dados obrigatórios
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
            
            # Se a distância não foi recebida, calcular usando x e y
            if data['distance'] is None:
                data['distance'] = math.sqrt(data['x_point']**2 + data['y_point']**2) * 100  # Converter para cm
            
            # Se não recebemos dados de batimentos/respiração, usar valores padrão
            if data['heart_rate'] is None:
                data['heart_rate'] = 75.0  # Valor padrão
                
            if data['breath_rate'] is None:
                data['breath_rate'] = 15.0  # Valor padrão
            
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
        
    def adjust_scale(self, value):
        """Ajusta a escala das coordenadas do radar"""
        return value * self.SCALE_FACTOR
        
    def initialize_database(self, db_manager):
        """Inicializa a tabela de seções da gôndola"""
        try:
            # Criar tabela para seções da gôndola
            db_manager.cursor.execute("""
                CREATE TABLE IF NOT EXISTS shelf_sections (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    section_name VARCHAR(50),
                    x_start FLOAT,
                    y_start FLOAT,
                    x_end FLOAT,
                    y_end FLOAT,
                    product_id VARCHAR(50),
                    product_name VARCHAR(100),
                    last_updated DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    is_active BOOLEAN DEFAULT TRUE
                )
            """)
            db_manager.conn.commit()
            logger.info("✅ Tabela shelf_sections criada/verificada com sucesso!")
            
        except Exception as e:
            logger.error(f"❌ Erro ao inicializar tabela shelf_sections: {str(e)}")
            logger.error(traceback.format_exc())
            raise
            
    def get_section_at_position(self, x, y, db_manager):
        """Identifica a seção baseada nas coordenadas (x, y)"""
        try:
            # Ajustar escala das coordenadas
            x_adjusted = self.adjust_scale(x)
            y_adjusted = self.adjust_scale(y)
            
            logger.debug(f"Coordenadas originais: ({x:.2f}cm, {y:.2f}cm)")
            logger.debug(f"Coordenadas ajustadas: ({x_adjusted:.2f}cm, {y_adjusted:.2f}cm)")
            
            query = """
                SELECT id, section_name, product_id, x_start, x_end, y_start, y_end 
                FROM shelf_sections 
                WHERE x_start * 100 <= %s AND x_end * 100 >= %s 
                AND y_start * 100 <= %s AND y_end * 100 >= %s 
                AND is_active = TRUE
            """
            db_manager.cursor.execute(query, (x_adjusted, x_adjusted, y_adjusted, y_adjusted))
            result = db_manager.cursor.fetchone()
            
            if result:
                section = {
                    'section_id': result['id'],
                    'section_name': result['section_name'],
                    'product_id': result['product_id'],
                    'x_start': self.adjust_scale(result['x_start']),
                    'x_end': self.adjust_scale(result['x_end']),
                    'y_start': self.adjust_scale(result['y_start']),
                    'y_end': self.adjust_scale(result['y_end'])
                }
                logger.info(f"Seção encontrada: {section['section_name']} (ID: {section['section_id']})")
                logger.debug(f"Coordenadas da seção: ({section['x_start']:.1f}cm,{section['y_start']:.1f}cm) - ({section['x_end']:.1f}cm,{section['y_end']:.1f}cm)")
                return section
                
            logger.warning(f"Nenhuma seção encontrada para posição ({x:.2f}cm, {y:.2f}cm)")
            return None
            
        except Exception as e:
            logger.error(f"Erro ao buscar seção: {str(e)}")
            logger.error(traceback.format_exc())
            return None
        
    def add_section(self, section_data, db_manager):
        """
        Adiciona uma nova seção à gôndola
        section_data: dict com section_name, x_start, y_start, x_end, y_end, product_id, product_name
        """
        try:
            query = """
                INSERT INTO shelf_sections
                (section_name, x_start, y_start, x_end, y_end, product_id, product_name)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """
            
            params = (
                section_data['section_name'],
                section_data['x_start'],
                section_data['y_start'],
                section_data['x_end'],
                section_data['y_end'],
                section_data['product_id'],
                section_data['product_name']
            )
            
            db_manager.cursor.execute(query, params)
            db_manager.conn.commit()
            
            logger.info(f"✅ Seção {section_data['section_name']} adicionada com sucesso!")
            return True
            
        except Exception as e:
            logger.error(f"❌ Erro ao adicionar seção: {str(e)}")
            logger.error(traceback.format_exc())
            return False
            
    def get_all_sections(self, db_manager):
        """Retorna todas as seções ativas"""
        try:
            query = """
                SELECT * FROM shelf_sections
                WHERE is_active = TRUE
                ORDER BY section_name
            """
            
            db_manager.cursor.execute(query)
            sections = db_manager.cursor.fetchall()
            
            return sections
            
        except Exception as e:
            logger.error(f"❌ Erro ao buscar seções: {str(e)}")
            logger.error(traceback.format_exc())
            return []

    def initialize_sections(self, db_manager):
        """Inicializa as seções padrão da prateleira"""
        try:
            logger.info("Iniciando a inicialização das seções...")
            
            # Seções padrão (coordenadas em metros no banco)
            default_sections = [
                {
                    'section_name': 'Granolas Premium',
                    'product_id': '1',
                    'product_name': 'Granola Premium',
                    'x_start': 0.0,
                    'y_start': 0.0,
                    'x_end': 0.5,
                    'y_end': 0.3
                },
                {
                    'section_name': 'Mix de Frutas Secas',
                    'product_id': '2',
                    'product_name': 'Mix de Frutas Secas',
                    'x_start': 0.5,
                    'y_start': 0.0,
                    'x_end': 1.0,
                    'y_end': 0.3
                },
                {
                    'section_name': 'Barras de Cereais',
                    'product_id': '3',
                    'product_name': 'Barras de Cereais',
                    'x_start': 1.0,
                    'y_start': 0.0,
                    'x_end': 1.5,
                    'y_end': 0.3
                }
            ]
            
            for section in default_sections:
                logger.info(f"Adicionando seção: {section['section_name']}")
                logger.debug(f"Coordenadas: ({section['x_start']}m,{section['y_start']}m) - ({section['x_end']}m,{section['y_end']}m)")
                self.add_section(section, db_manager)
                
            logger.info("Inicialização das seções concluída com sucesso!")
            return True
            
        except Exception as e:
            logger.error(f"Erro ao inicializar seções: {str(e)}")
            logger.error(traceback.format_exc())
            return False

# Instância global do gerenciador de seções
shelf_manager = ShelfManager()

class DatabaseManager:
    def __init__(self):
        self.conn = None
        self.cursor = None
        self.last_sequence = 0
        self.last_move_speed = None
        self.connect_with_retry()
        
    def connect_with_retry(self, max_attempts=5):
        """Tenta conectar ao banco com retry"""
        attempt = 0
        while attempt < max_attempts:
            try:
                attempt += 1
                logger.info(f"Tentativa {attempt} de {max_attempts} para conectar ao banco...")
                
                if self.conn:
                    try:
                        self.conn.close()
                    except:
                        pass
                
                self.conn = mysql.connector.connect(**DB_CONFIG)
                self.cursor = self.conn.cursor(dictionary=True, buffered=True)
                
                # Testar conexão
                self.cursor.execute("SELECT 1")
                self.cursor.fetchone()
                
                logger.info("✅ Conexão estabelecida com sucesso!")
                self.initialize_database()
                return True
                
            except Exception as e:
                logger.error(f"❌ Tentativa {attempt} falhou: {str(e)}")
                if attempt == max_attempts:
                    logger.error("Todas as tentativas de conexão falharam!")
                    raise
                time.sleep(2)
        return False

    def initialize_database(self):
        """Inicializa o banco de dados e cria as tabelas necessárias"""
        try:
            # Verificar tabela radar_dados
            logger.info("Verificando tabela radar_dados...")
            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS radar_dados (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    x_point FLOAT,
                    y_point FLOAT,
                    move_speed FLOAT,
                    heart_rate FLOAT,
                    breath_rate FLOAT,
                    satisfaction_score FLOAT,
                    satisfaction_class VARCHAR(20),
                    is_engaged BOOLEAN,
                    engagement_duration INT,
                    session_id VARCHAR(36),
                    section_id INT,
                    product_id VARCHAR(20),
                    timestamp DATETIME,
                    serial_number VARCHAR(20),
                    distance FLOAT,
                    dop_index INT,
                    cluster_index INT
                )
            """)
            self.conn.commit()
            logger.info("✅ Tabela radar_dados criada/verificada com sucesso!")

            # Verificar tabela radar_sessoes
            logger.info("Verificando tabela radar_sessoes...")
            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS radar_sessoes (
                    session_id VARCHAR(50) PRIMARY KEY,
                    start_time DATETIME,
                    end_time DATETIME,
                    duration INT,
                    avg_heart_rate FLOAT,
                    avg_breath_rate FLOAT,
                    avg_satisfaction FLOAT,
                    satisfaction_class VARCHAR(20),
                    is_engaged BOOLEAN,
                    data_points INT
                )
            """)
            self.conn.commit()
            logger.info("✅ Tabela radar_sessoes criada/verificada com sucesso!")

            # Verificar tabela shelf_sections
            shelf_manager.initialize_database(self)
            
            logger.info("✅ Banco de dados inicializado com sucesso!")
            return True

        except Exception as e:
            logger.error(f"❌ Erro ao inicializar banco: {str(e)}")
            logger.error(traceback.format_exc())
            return False

    def insert_radar_data(self, data, attempt=0, max_retries=3, retry_delay=1):
        """Insere dados do radar no banco de dados"""
        try:
            # Calcular duração do engajamento (em segundos)
            if not hasattr(self, 'last_engagement_time'):
                self.last_engagement_time = None
            
            if data.get('is_engaged'):
                if self.last_engagement_time:
                    engagement_duration = int((datetime.now() - self.last_engagement_time).total_seconds())
                else:
                    engagement_duration = 0
                self.last_engagement_time = datetime.now()
            else:
                engagement_duration = 0
                self.last_engagement_time = None
            
            # Query de inserção
            query = """
                INSERT INTO radar_dados
                (x_point, y_point, move_speed, heart_rate, breath_rate, 
                satisfaction_score, satisfaction_class, is_engaged, engagement_duration,
                session_id, section_id, product_id, timestamp, serial_number,
                distance, dop_index)
                VALUES ({}, {}, {}, {}, {}, {}, '{}', {}, {}, '{}', {}, '{}', '{}', '{}', {}, {})
            """.format(
                float(data.get('x_point', 0)),
                float(data.get('y_point', 0)),
                float(data.get('move_speed', 0)),
                'NULL' if data.get('heart_rate') is None else float(data.get('heart_rate')),
                'NULL' if data.get('breath_rate') is None else float(data.get('breath_rate')),
                float(data.get('satisfaction_score', 50.0)),
                data.get('satisfaction_class', 'NEUTRA'),
                1 if data.get('is_engaged', False) else 0,
                engagement_duration,
                data.get('session_id', str(uuid.uuid4())),
                'NULL' if data.get('section_id') is None else int(data.get('section_id')),
                data.get('product_id', 'UNKNOWN'),
                data.get('timestamp', datetime.now().strftime('%Y-%m-%d %H:%M:%S')),
                data.get('serial_number', 'RADAR_1'),
                float(data.get('distance', 0)),
                int(data.get('dop_index', 0))
            )
            
            # Log detalhado para debug
            logger.debug("Executando query de inserção:")
            logger.debug(f"Query formatada: {query}")
            
            # Executar inserção com retry em caso de deadlock
            try:
                self.cursor.execute(query)
                self.conn.commit()
                logger.debug("✅ Query executada com sucesso!")
                return True
            except mysql.connector.errors.DatabaseError as e:
                if e.errno == 1205 and attempt < max_retries - 1:  # Lock timeout error
                    logger.warning(f"Lock timeout na tentativa {attempt + 1}, tentando novamente em {retry_delay} segundos...")
                    time.sleep(retry_delay)
                    return self.insert_radar_data(data, attempt + 1, max_retries, retry_delay)
                raise
            
        except Exception as e:
            logger.error(f"❌ Erro ao inserir dados: {str(e)}")
            logger.error(traceback.format_exc())
            if attempt < max_retries - 1:
                logger.info(f"Tentando novamente em {retry_delay} segundos...")
                time.sleep(retry_delay)
                return self.insert_radar_data(data, attempt + 1, max_retries, retry_delay)
            return False

class AnalyticsManager:
    def __init__(self):
        # Constantes para cálculo de satisfação
        self.MOVEMENT_THRESHOLD = 20.0  # cm/s
        self.DISTANCE_THRESHOLD = 2.0   # metros
        self.HEART_RATE_NORMAL = (60, 100)  # bpm
        self.BREATH_RATE_NORMAL = (12, 20)  # rpm
        
    def calculate_satisfaction_score(self, move_speed, heart_rate, breath_rate, distance):
        """
        Calcula o score de satisfação baseado nos dados do radar
        Retorna: (score, classificação)
        """
        try:
            score = 0.0
            
            # Pontuação baseada na velocidade de movimento
            if move_speed is not None:
                if move_speed <= self.MOVEMENT_THRESHOLD:
                    score += 30  # Pessoa parada/interessada
                else:
                    score += max(0, 30 * (1 - move_speed/100))  # Diminui conforme velocidade aumenta
            
            # Pontuação baseada na distância
            if distance is not None:
                if distance <= self.DISTANCE_THRESHOLD:
                    score += 20  # Pessoa próxima
                else:
                    score += max(0, 20 * (1 - distance/5))  # Diminui conforme distância aumenta
            
            # Pontuação baseada nos batimentos cardíacos
            if heart_rate is not None:
                if self.HEART_RATE_NORMAL[0] <= heart_rate <= self.HEART_RATE_NORMAL[1]:
                    score += 25  # Batimentos normais
                else:
                    # Penalidade para batimentos muito altos ou baixos
                    deviation = min(
                        abs(heart_rate - self.HEART_RATE_NORMAL[0]),
                        abs(heart_rate - self.HEART_RATE_NORMAL[1])
                    )
                    score += max(0, 25 * (1 - deviation/50))
            
            # Pontuação baseada na respiração
            if breath_rate is not None:
                if self.BREATH_RATE_NORMAL[0] <= breath_rate <= self.BREATH_RATE_NORMAL[1]:
                    score += 25  # Respiração normal
                else:
                    # Penalidade para respiração muito alta ou baixa
                    deviation = min(
                        abs(breath_rate - self.BREATH_RATE_NORMAL[0]),
                        abs(breath_rate - self.BREATH_RATE_NORMAL[1])
                    )
                    score += max(0, 25 * (1 - deviation/20))
            
            # Classificar satisfação
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
            return (50.0, "NEUTRA")  # Valor padrão em caso de erro

class VitalSignsManager:
    def __init__(self):
        # Configurações de buffer e amostragem
        self.SAMPLE_RATE = 20  # Aumentado para 20Hz (50ms entre amostras)
        
        # Buffers para diferentes sinais
        self.heart_phase_buffer = []
        self.breath_phase_buffer = []
        self.quality_buffer = []  # Buffer para qualidade do sinal
        
        # Configurações de buffer - Reduzido para melhor resposta
        self.HEART_BUFFER_SIZE = 20   # 1 segundo para batimentos
        self.BREATH_BUFFER_SIZE = 30  # 1.5 segundos para respiração
        self.QUALITY_BUFFER_SIZE = 10 # 0.5 segundos para qualidade
        
        # Últimas leituras válidas
        self.last_heart_rate = None
        self.last_breath_rate = None
        self.last_quality_score = 0
        
        # Thresholds e parâmetros ajustados
        self.MIN_QUALITY_SCORE = 0.3  # Reduzido para 30% de qualidade mínima
        self.STABILITY_THRESHOLD = 0.4  # Aumentado para 40% de variação permitida
        self.VALID_RANGES = {
            'heart_rate': (40, 140),  # Range mais amplo para batimentos
            'breath_rate': (8, 25)    # Range mantido para respiração
        }
        
        # Histórico para detecção de tendências
        self.heart_rate_history = []
        self.breath_rate_history = []
        self.HISTORY_SIZE = 10  # Manter histórico das últimas 10 leituras válidas
        
    def calculate_signal_quality(self, phase_data, distance):
        """
        Calcula um score de qualidade do sinal baseado em vários fatores
        """
        try:
            if not phase_data or len(phase_data) < 5:
                return 0.0
                
            # Fator de distância (melhor qualidade entre 30cm e 100cm)
            distance_score = 1.0
            if distance < 30 or distance > 150:
                distance_score = 0.0
            elif distance > 100:
                distance_score = 1.0 - ((distance - 100) / 50)
            
            # Fator de variância (sinais estáveis têm menor variância)
            variance = np.var(phase_data)
            variance_score = 1.0 / (1.0 + variance * 10)
            
            # Fator de amplitude (sinais muito fracos ou fortes demais são ruins)
            amplitude = np.ptp(phase_data)
            amplitude_score = 1.0
            if amplitude < 0.01 or amplitude > 1.0:
                amplitude_score = 0.5
            
            # Score final ponderado
            quality_score = (distance_score * 0.3 + 
                           variance_score * 0.4 + 
                           amplitude_score * 0.3)
            
            # Atualizar buffer de qualidade
            self.quality_buffer.append(quality_score)
            if len(self.quality_buffer) > self.QUALITY_BUFFER_SIZE:
                self.quality_buffer.pop(0)
            
            # Usar média móvel para suavizar mudanças bruscas
            self.last_quality_score = np.mean(self.quality_buffer)
            
            return self.last_quality_score
            
        except Exception as e:
            logger.error(f"Erro ao calcular qualidade do sinal: {str(e)}")
            return 0.0
    
    def calculate_vital_signs(self, total_phase, breath_phase, heart_phase, distance):
        """
        Calcula os sinais vitais com melhor validação e filtros
        """
        try:
            # Calcular qualidade do sinal
            quality_score = self.calculate_signal_quality(heart_phase, distance)
            logger.debug(f"Qualidade do sinal: {quality_score:.2f}")
            
            if quality_score < self.MIN_QUALITY_SCORE:
                logger.debug(f"⚠️ Qualidade do sinal muito baixa: {quality_score:.2f}")
                return None, None
            
            # Atualizar buffers com tamanhos diferentes para cada sinal
            self.heart_phase_buffer.append(heart_phase)
            self.breath_phase_buffer.append(breath_phase)
            
            # Manter tamanho dos buffers
            while len(self.heart_phase_buffer) > self.HEART_BUFFER_SIZE:
                self.heart_phase_buffer.pop(0)
            while len(self.breath_phase_buffer) > self.BREATH_BUFFER_SIZE:
                self.breath_phase_buffer.pop(0)
            
            # Verificar se temos dados suficientes
            if len(self.heart_phase_buffer) < self.HEART_BUFFER_SIZE * 0.7:  # Reduzido para 70%
                logger.debug(f"⏳ Aguardando mais dados ({len(self.heart_phase_buffer)}/{self.HEART_BUFFER_SIZE})")
                return None, None
            
            # Aplicar filtro de média móvel ponderada para suavização
            heart_weights = np.hamming(len(self.heart_phase_buffer))
            breath_weights = np.hamming(len(self.breath_phase_buffer))
            
            heart_smooth = np.average(self.heart_phase_buffer, weights=heart_weights)
            breath_smooth = np.average(self.breath_phase_buffer, weights=breath_weights)
            
            # Calcular taxas com dados suavizados
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
            
            # Validar resultados
            if heart_rate:
                # Verificar estabilidade em relação à última leitura
                if self.last_heart_rate:
                    rate_change = abs(heart_rate - self.last_heart_rate) / self.last_heart_rate
                    if rate_change > self.STABILITY_THRESHOLD:
                        logger.debug(f"⚠️ Mudança brusca nos batimentos: {rate_change:.2f}")
                        # Em vez de descartar, usar média com último valor
                        heart_rate = (heart_rate + self.last_heart_rate) / 2
                    else:
                        self.last_heart_rate = heart_rate
                else:
                    self.last_heart_rate = heart_rate
                
                # Atualizar histórico
                self.heart_rate_history.append(heart_rate)
                if len(self.heart_rate_history) > self.HISTORY_SIZE:
                    self.heart_rate_history.pop(0)
            
            if breath_rate:
                # Verificar estabilidade em relação à última leitura
                if self.last_breath_rate:
                    rate_change = abs(breath_rate - self.last_breath_rate) / self.last_breath_rate
                    if rate_change > self.STABILITY_THRESHOLD:
                        logger.debug(f"⚠️ Mudança brusca na respiração: {rate_change:.2f}")
                        breath_rate = None
                    else:
                        self.last_breath_rate = breath_rate
                else:
                    self.last_breath_rate = breath_rate
                
                # Atualizar histórico
                self.breath_rate_history.append(breath_rate)
                if len(self.breath_rate_history) > self.HISTORY_SIZE:
                    self.breath_rate_history.pop(0)
            
            # Log detalhado
            if heart_rate and breath_rate:
                logger.debug(f"✅ Medição válida - HR: {heart_rate:.1f} bpm, BR: {breath_rate:.1f} rpm")
            
            return heart_rate, breath_rate
            
        except Exception as e:
            logger.error(f"Erro ao calcular sinais vitais: {str(e)}")
            logger.error(traceback.format_exc())
            return None, None
    
    def _calculate_rate_from_phase(self, phase_data, min_freq, max_freq, rate_multiplier):
        """
        Calcula a frequência dominante no sinal de fase usando FFT
        """
        try:
            if not phase_data:
                return None
                
            # Remover média do sinal (centralizar em zero)
            phase_mean = np.mean(phase_data)
            centered_phase = np.array(phase_data) - phase_mean
            
            # Aplicar janela Hanning para reduzir vazamento espectral
            window = np.hanning(len(centered_phase))
            windowed_phase = centered_phase * window
            
            # Calcular FFT
            fft_result = np.fft.fft(windowed_phase)
            fft_freq = np.fft.fftfreq(len(windowed_phase), d=1/self.SAMPLE_RATE)
            
            # Considerar apenas frequências positivas dentro do range desejado
            valid_idx = np.where((fft_freq >= min_freq) & (fft_freq <= max_freq))[0]
            if len(valid_idx) == 0:
                return None
                
            # Encontrar frequência dominante
            magnitude_spectrum = np.abs(fft_result[valid_idx])
            peak_idx = np.argmax(magnitude_spectrum)
            dominant_freq = fft_freq[valid_idx[peak_idx]]
            
            # Verificar se o pico é significativo
            peak_magnitude = magnitude_spectrum[peak_idx]
            avg_magnitude = np.mean(magnitude_spectrum)
            if peak_magnitude < 1.5 * avg_magnitude:  # Pico deve ser 50% maior que a média
                return None
            
            # Converter para BPM/RPM
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
        """Tenta encontrar a porta serial do dispositivo automaticamente"""
        import serial.tools.list_ports
        
        # Listar todas as portas seriais disponíveis
        ports = list(serial.tools.list_ports.comports())
        if not ports:
            logger.error("Nenhuma porta serial encontrada!")
            return None
            
        # Procurar por portas que pareçam ser dispositivos ESP32 ou Arduino
        for port in ports:
            desc_lower = port.description.lower()
            if any(term in desc_lower for term in 
                  ['usb', 'serial', 'uart', 'cp210', 'ch340', 'ft232', 'arduino', 'esp32']):
                logger.info(f"Porta serial encontrada: {port.device} ({port.description})")
                return port.device
                
        # Se não encontrou nenhuma específica, usar a primeira da lista
        logger.info(f"Usando primeira porta serial disponível: {ports[0].device}")
        return ports[0].device
    
    def connect(self):
        """Estabelece conexão com a porta serial"""
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
            # Pequeno delay para garantir que a conexão esteja estabilizada
            time.sleep(2)
            logger.info(f"✅ Conexão serial estabelecida com sucesso!")
            return True
        except Exception as e:
            logger.error(f"❌ Erro ao conectar à porta serial: {str(e)}")
            logger.error(traceback.format_exc())
            return False
            
    def start(self, db_manager):
        """Inicia o receptor de dados seriais em uma thread separada"""
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
        """Para o receptor de dados seriais"""
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
        """Loop principal para receber e processar dados da porta serial"""
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
                    
                # Ler dados disponíveis
                in_waiting = self.serial_connection.in_waiting
                if in_waiting is None:
                    in_waiting = 0
                
                data = self.serial_connection.read(in_waiting or 1)
                if data:
                    last_data_time = time.time()
                    text = data.decode('utf-8', errors='ignore')
                    buffer += text
                    
                    # Verificar se temos linhas completas
                    if '\n' in buffer:
                        lines = buffer.split('\n')
                        buffer = lines[-1]  # Manter o que sobrar após o último newline
                        
                        # Processar linhas completas
                        for line in lines[:-1]:
                            line = line.strip()
                            
                            # Início de uma mensagem de detecção
                            if '-----Human Detected-----' in line:
                                message_mode = True
                                message_buffer = line + '\n'
                                target_data_complete = False
                            # Continuação da mensagem de detecção
                            elif message_mode:
                                message_buffer += line + '\n'
                                
                                # Verificar se a mensagem está completa
                                if 'distance:' in line:  # Último campo enviado pelo radar
                                    target_data_complete = True
                                    # Processar os dados coletados
                                    self.process_radar_data(message_buffer)
                                    message_mode = False
                                    message_buffer = ""
                                    target_data_complete = False
                            
                # Verificar se está recebendo dados
                if time.time() - last_data_time > 5:  # 5 segundos sem dados
                    logger.warning("⚠️ Nenhum dado recebido nos últimos 5 segundos")
                    last_data_time = time.time()
                    
                # Pequena pausa para evitar consumo excessivo de CPU
                time.sleep(0.01)
                
            except Exception as e:
                logger.error(f"❌ Erro no loop de recepção: {str(e)}")
                logger.error(traceback.format_exc())
                time.sleep(1)  # Pausa para evitar spam de logs em caso de erro
                
    def process_radar_data(self, raw_data):
        """Processa dados brutos do radar recebidos pela serial"""
        try:
            # Converter dados
            data = parse_serial_data(raw_data)
            if not data:
                return
            # Calcular sinais vitais usando os dados de fase
            heart_rate, breath_rate = self.vital_signs_manager.calculate_vital_signs(
                data.get('total_phase', 0),
                data.get('breath_phase', 0),
                data.get('heart_phase', 0),
                data.get('distance', 0)
            )
            # Calcular distância se não foi fornecida
            distance = data.get('distance', 0)
            if distance == 0:
                x = data.get('x_point', 0)
                y = data.get('y_point', 0)
                distance = (x**2 + y**2)**0.5
                logger.debug(f"Distância calculada: {distance:.2f}cm")
            # Calcular velocidade de movimento usando dop_index
            dop_index = data.get('dop_index', 0)
            move_speed = abs(dop_index * RANGE_STEP) if dop_index is not None else 0
            logger.debug(f"Velocidade calculada: {move_speed:.2f}cm/s (dop_index: {dop_index})")
            # Criar dicionário com dados convertidos
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
            # Identificar seção baseado na posição
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
            # Substituir ML por lógica simples ou valores padrão
            is_engaged = False
            engagement_prob = 0.0
            converted_data['is_engaged'] = is_engaged
            converted_data['engagement_probability'] = engagement_prob
            satisfaction_score = 50.0
            converted_data['satisfaction_score'] = satisfaction_score
            # Classificar satisfação baseado no score
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
            converted_data['purchase_probability'] = 0.0
            converted_data['customer_cluster'] = "default"
            # Exibir dados formatados no terminal
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
            print(f"   Engajado: {'✅ Sim' if is_engaged else '❌ Não'} (Prob: {engagement_prob:.2%})")
            print(f"   Score: {converted_data['satisfaction_score']:.1f}")
            print(f"   Classificação: {converted_data['satisfaction_class']}")
            print(f"   Prob. Compra: {converted_data['purchase_probability']:.2%}")
            print(f"   Segmento: {converted_data['customer_cluster']}")
            print("="*50)
            print("")  # Linha extra para melhor separação entre leituras
            # Inserir dados no banco
            if self.db_manager:
                try:
                    success = self.db_manager.insert_radar_data(converted_data)
                    if success:
                        logger.debug("✅ Dados salvos no banco com sucesso!")
                    else:
                        logger.error("❌ Falha ao salvar dados no banco")
                except Exception as e:
                    logger.error(f"❌ Erro ao salvar no banco: {str(e)}")
                    logger.error(traceback.format_exc())
            else:
                logger.warning("⚠️ Gerenciador de banco de dados não disponível")
        except Exception as e:
            logger.error(f"❌ Erro ao processar dados: {str(e)}")
            logger.error(traceback.format_exc())

def main():
    # Inicializar gerenciador de banco de dados
    logger.info("Iniciando DatabaseManager...")
    try:
        db_manager = DatabaseManager()
        logger.info("✅ DatabaseManager iniciado com sucesso!")
    except Exception as e:
        logger.error(f"❌ Erro ao criar instância do DatabaseManager: {e}")
        logger.error(traceback.format_exc())
        return

    # Inicializar gerenciador de radar serial
    port = os.getenv("SERIAL_PORT")  # Obter da variável de ambiente ou buscar automaticamente
    baudrate = int(os.getenv("SERIAL_BAUDRATE", "115200"))
    
    radar_manager = SerialRadarManager(port, baudrate)
    
    try:
        # Iniciar o receptor
        logger.info(f"Iniciando SerialRadarManager...")
        success = radar_manager.start(db_manager)
        
        if not success:
            logger.error("❌ Falha ao iniciar o gerenciador de radar serial")
            return
            
        logger.info("="*50)
        logger.info("🚀 Sistema Radar Serial iniciado com sucesso!")
        logger.info(f"📡 Porta serial: {radar_manager.port}")
        logger.info(f"📡 Baudrate: {radar_manager.baudrate}")
        logger.info("⚡ Pressione Ctrl+C para encerrar")
        logger.info("="*50)
        
        # Manter o programa rodando
        while True:
            time.sleep(1)
            
    except KeyboardInterrupt:
        logger.info("Encerrando por interrupção do usuário...")
        
    finally:
        # Parar o receptor
        radar_manager.stop()
        logger.info("Sistema encerrado!")

if __name__ == "__main__":
    main() 
