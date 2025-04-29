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

# Constante para conversão do índice Doppler para velocidade
RANGE_STEP = 2.5  # Valor do RANGE_STEP do código ESP32/Arduino

def parse_serial_data(raw_data):
    """Analisa os dados brutos da porta serial para extrair informações do radar mmWave"""
    try:
        # Padrões atualizados para o formato real dos dados
        x_pattern = r'x_point:\s*([-]?\d+\.\d+)'
        y_pattern = r'y_point:\s*([-]?\d+\.\d+)'
        speed_pattern = r'move_speed:\s*([-]?\d+\.\d+)\s*cm/s'
        heart_pattern = r'heart_rate:\s*([-]?\d+\.\d+)'
        breath_pattern = r'breath_rate:\s*([-]?\d+\.\d+)'
        distance_pattern = r'distance:\s*([-]?\d+\.\d+)'
        
        # Novos padrões para fases
        heart_phase_pattern = r'heart_phase:\s*([-]?\d+\.\d+)'
        breath_phase_pattern = r'breath_phase:\s*([-]?\d+\.\d+)'
        total_phase_pattern = r'total_phase:\s*([-]?\d+\.\d+)'
        
        # Extrair valores usando expressões regulares
        x_match = re.search(x_pattern, raw_data)
        y_match = re.search(y_pattern, raw_data)
        speed_match = re.search(speed_pattern, raw_data)
        heart_match = re.search(heart_pattern, raw_data)
        breath_match = re.search(breath_pattern, raw_data)
        distance_match = re.search(distance_pattern, raw_data)
        
        # Extrair fases
        heart_phase_match = re.search(heart_phase_pattern, raw_data)
        breath_phase_match = re.search(breath_phase_pattern, raw_data)
        total_phase_match = re.search(total_phase_pattern, raw_data)
        
        if '-----Human Detected-----' in raw_data and 'Target #1' in raw_data:
            # Dados obrigatórios
            x_point = float(x_match.group(1)) if x_match else 0.0
            y_point = float(y_match.group(1)) if y_match else 0.0
            
            # Calcular distância do sensor
            distance = float(distance_match.group(1)) if distance_match else math.sqrt(x_point**2 + y_point**2)
            
            # Velocidade de movimento
            move_speed = float(speed_match.group(1)) if speed_match else 0.0
            
            # Sinais vitais
            heart_rate = float(heart_match.group(1)) if heart_match else 75.0
            breath_rate = float(breath_match.group(1)) if breath_match else 15.0
            
            # Dados adicionais de fase
            heart_phase = float(heart_phase_match.group(1)) if heart_phase_match else 0.0
            breath_phase = float(breath_phase_match.group(1)) if breath_phase_match else 0.0
            total_phase = float(total_phase_match.group(1)) if total_phase_match else 0.0
            
            logger.debug(f"Dados extraídos com sucesso: x={x_point}, y={y_point}, speed={move_speed}")
            
            return {
                'x_point': x_point,
                'y_point': y_point,
                'move_speed': move_speed,
                'heart_rate': heart_rate,
                'breath_rate': breath_rate,
                'distance': distance,
                'heart_phase': heart_phase,
                'breath_phase': breath_phase,
                'total_phase': total_phase
            }
        else:
            # Se não for possível extrair todos os valores necessários
            if '-----Human Detected-----' in raw_data:
                logger.info("Detecção humana sem informações detalhadas")
            elif raw_data.strip():
                logger.debug(f"Dados incompletos: {raw_data}")
            return None
            
    except Exception as e:
        logger.error(f"Erro ao analisar dados seriais: {str(e)}")
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
        self.SECTION_WIDTH = 0.5  # Largura de cada seção em metros
        self.SECTION_HEIGHT = 0.3  # Altura de cada seção em metros
        self.MAX_SECTIONS_X = 4    # Número máximo de seções na horizontal
        self.MAX_SECTIONS_Y = 3    # Número máximo de seções na vertical
        
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
            query = """
                SELECT id, section_name, product_id, x_start, x_end, y_start, y_end 
                FROM shelf_sections 
                WHERE x_start <= %s AND x_end >= %s 
                AND y_start <= %s AND y_end >= %s 
                AND is_active = TRUE
            """
            db_manager.cursor.execute(query, (x, x, y, y))
            result = db_manager.cursor.fetchone()
            
            if result:
                return {
                    'section_id': result[0],
                    'section_name': result[1],
                    'product_id': result[2],
                    'x_start': result[3],
                    'x_end': result[4],
                    'y_start': result[5],
                    'y_end': result[6]
                }
            return None
            
        except Exception as e:
            logger.error(f"Erro ao buscar seção: {str(e)}")
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

# Instância global do gerenciador de seções
shelf_manager = ShelfManager()

# Configurações do MySQL
db_config = {
    "host": os.getenv("DB_HOST", "168.75.89.11"),
    "user": os.getenv("DB_USER", "belugaDB"),
    "password": os.getenv("DB_PASSWORD", "Rpcr@300476"),
    "database": os.getenv("DB_NAME", "Beluga_Analytics"),
    "port": int(os.getenv("DB_PORT", 3306)),
    "use_pure": True,
    "ssl_disabled": True
}

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
                
                self.conn = mysql.connector.connect(**db_config)
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
                    serial_number VARCHAR(20)
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
            return False

    def insert_radar_data(self, data, attempt=0, max_retries=3, retry_delay=1):
        """Insere dados do radar no banco de dados"""
        try:
            # Query de inserção
            query = """
                INSERT INTO radar_dados
                (x_point, y_point, move_speed, heart_rate, breath_rate, 
                satisfaction_score, satisfaction_class, is_engaged, engagement_duration, 
                session_id, section_id, product_id, timestamp, serial_number)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
            
            # Preparar parâmetros
            params = (
                float(data.get('x_point')),
                float(data.get('y_point')),
                float(data.get('move_speed')),
                float(data.get('heart_rate')) if data.get('heart_rate') is not None else None,
                float(data.get('breath_rate')) if data.get('breath_rate') is not None else None,
                float(data.get('satisfaction_score', 0)),
                data.get('satisfaction_class', 'NEUTRA'),
                bool(data.get('is_engaged', False)),
                int(data.get('engagement_duration', 0)),
                data.get('session_id'),
                data.get('section_id'),  # Pode ser None
                data.get('product_id', 'UNKNOWN'),
                data.get('timestamp', datetime.now().strftime('%Y-%m-%d %H:%M:%S')),
                data.get('serial_number', 'RADAR_1')
            )
            
            logger.info(f"Query: {query}")
            logger.info(f"Parâmetros: {params}")
            
            # Executar inserção com retry em caso de deadlock
            try:
                self.cursor.execute(query, params)
                self.conn.commit()
                logger.info("✅ Dados inseridos com sucesso!")
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

class SerialRadarManager:
    def __init__(self, port=None, baudrate=115200):
        self.port = port or self.find_serial_port()
        self.baudrate = baudrate
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
        
        while self.is_running:
            try:
                if not self.serial_connection.is_open:
                    self.connect()
                    time.sleep(1)
                    continue
                    
                # Ler dados disponíveis
                data = self.serial_connection.read(self.serial_connection.in_waiting or 1)
                if data:
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
                                if ('breath_rate:' in line or 'breath_rate:' in message_buffer):
                                    target_data_complete = True
                                
                                # Verificar se temos outra detecção (novo Target) - fim da anterior
                                if target_data_complete and (line.strip() == '' or 'Target' in line and line.startswith('Target')):
                                    # Processar os dados coletados
                                    self.process_radar_data(message_buffer)
                                    
                                    # Se for uma linha em branco, finalizar a mensagem
                                    if line.strip() == '':
                                        message_mode = False
                                        message_buffer = ""
                                        target_data_complete = False
                                    # Se for outro Target, começar novo ciclo mas manter o modo
                                    else:
                                        message_buffer = line + '\n'
                                        target_data_complete = False
                            # Outras mensagens não relacionadas à detecção
                            elif line:
                                logger.debug(f"Mensagem: {line}")
                                
                # Pequena pausa para evitar consumo excessivo de CPU
                time.sleep(0.01)
                
            except Exception as e:
                logger.error(f"❌ Erro no loop de recepção: {str(e)}")
                logger.error(traceback.format_exc())
                time.sleep(1)  # Pausa para evitar spam de logs em caso de erro
                
    def process_radar_data(self, raw_data):
        """Processa dados brutos do radar recebidos pela serial"""
        logger.info("="*50)
        logger.info("📡 NOVOS DADOS RECEBIDOS")
        logger.info("="*50)
        
        # Converter dados
        converted_data = convert_radar_data(raw_data)
        if not converted_data:
            logger.warning("⚠️ Não foi possível extrair dados do radar desta mensagem")
            return
            
        # Adicionar timestamp atual
        converted_data['timestamp'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        logger.info(f"⏰ Timestamp: {converted_data['timestamp']}")
        
        # Identificar seção baseado na posição
        section = shelf_manager.get_section_at_position(
            converted_data['x_point'],
            converted_data['y_point'],
            self.db_manager
        )
        
        if section:
            converted_data['section_id'] = section['section_id']
            converted_data['product_id'] = section['product_id']
            logger.info(f"📍 Seção: {section['section_name']}")
            logger.info(f"📦 Produto: {section['product_id']}")
        else:
            converted_data['section_id'] = None
            converted_data['product_id'] = None
            logger.warning("❌ Nenhuma seção detectada para esta posição")
            
        # Calcular satisfação
        satisfaction_data = self.analytics_manager.calculate_satisfaction_score(
            converted_data.get('move_speed'),
            converted_data.get('heart_rate'),
            converted_data.get('breath_rate'),
            converted_data.get('distance', 2.0)
        )
        
        converted_data['satisfaction_score'] = satisfaction_data[0]
        converted_data['satisfaction_class'] = satisfaction_data[1]
        
        # Calcular engajamento
        is_engaged = converted_data.get('move_speed', float('inf')) <= self.analytics_manager.MOVEMENT_THRESHOLD
        converted_data['is_engaged'] = is_engaged
        
        # Log dos dados calculados
        logger.info("\n📊 DADOS PROCESSADOS:")
        logger.info(f"   Posição X: {converted_data['x_point']:.2f}m")
        logger.info(f"   Posição Y: {converted_data['y_point']:.2f}m")
        logger.info(f"   Velocidade: {converted_data['move_speed']:.2f} cm/s")
        logger.info(f"   Batimentos: {converted_data['heart_rate']:.1f} bpm")
        logger.info(f"   Respiração: {converted_data['breath_rate']:.1f} rpm")
        logger.info(f"\n🎯 STATUS:")
        logger.info(f"   Engajado: {'✅ Sim' if is_engaged else '❌ Não'}")
        logger.info(f"   Satisfação: {satisfaction_data[0]:.1f} ({satisfaction_data[1]})")
        logger.info("="*50)
        
        # Inserir dados no banco
        if self.db_manager:
            success = self.db_manager.insert_radar_data(converted_data)
            if not success:
                logger.error("❌ Falha ao inserir dados no banco")
        else:
            logger.warning("⚠️ Gerenciador de banco de dados não disponível, dados não foram salvos")

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
