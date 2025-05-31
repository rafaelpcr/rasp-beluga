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
from collections import defaultdict
import json

# Configuração básica de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('dual_radar_counter.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('dual_radar_counter_app')

# Configurando o nível de log para outros módulos
logging.getLogger('urllib3').setLevel(logging.WARNING)
logging.getLogger('gspread').setLevel(logging.WARNING)

load_dotenv()

# Configurações dos radares com suas planilhas específicas
RADAR_CONFIGS = [
    {
        'id': 'RADAR_1',
        'name': 'Contador Entrada Estande',
        'port': '/dev/ttyACM0',  # Será detectado automaticamente
        'baudrate': 115200,
        'spreadsheet_id': '1zVVyL6D9XSrzFvtDxaGJ-3CdniD-gG3Q-bUUXyqr3D4',  # Planilha entrada estande
        'spreadsheet_name': 'contador_entrada_estande',
        'color': '🔴',
        'description': 'Conta pessoas entrando no estande'
    },
    {
        'id': 'RADAR_2', 
        'name': 'Contador Interno Estande',
        'port': '/dev/ttyACM1',  # Será detectado automaticamente
        'baudrate': 115200,
        'spreadsheet_id': '1ACu8Qmicxv7Av-1nAK_dIDbcD_RJBizk2iXspixK2Gg',  # Planilha interno estande
        'spreadsheet_name': 'contador_interno_estande',
        'color': '🔵',
        'description': 'Conta pessoas no interior do estande'
    }
]

RANGE_STEP = 2.5

class GoogleSheetsCounterManager:
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
        
        # Verifica e configura cabeçalhos para contagem de pessoas
        self._setup_counter_headers()

    def _setup_counter_headers(self):
        """Configura cabeçalhos para contagem de pessoas"""
        try:
            headers = self.worksheet.row_values(1)
            expected_headers = [
                'timestamp', 'session_id', 'event_type', 'current_count',
                'total_entries', 'total_exits', 'max_simultaneous',
                'person_id', 'x_position', 'y_position', 'distance', 'zone',
                'duration_in_area', 'speed', 'confidence_level', 'radar_id'
            ]
            
            if not headers or len(headers) < 10:
                logger.info(f"🔧 Configurando cabeçalhos de contagem para {self.radar_id}")
                self.worksheet.clear()
                self.worksheet.append_row(expected_headers)
            else:
                logger.info(f"✅ Cabeçalhos verificados para {self.radar_id}")
                # Adiciona radar_id se não existir
                if 'radar_id' not in headers:
                    next_col = len(headers) + 1
                    self.worksheet.update_cell(1, next_col, 'radar_id')
                    
        except Exception as e:
            logger.warning(f"⚠️ Erro ao configurar cabeçalhos para {self.radar_id}: {e}")

    def insert_counter_data(self, data):
        try:
            row = [
                data.get('timestamp'),
                data.get('session_id'),
                data.get('event_type'),
                data.get('current_count'),
                data.get('total_entries'),
                data.get('total_exits'),
                data.get('max_simultaneous'),
                data.get('person_id'),
                data.get('x_position'),
                data.get('y_position'),
                data.get('distance'),
                data.get('zone'),
                data.get('duration_in_area'),
                data.get('speed'),
                data.get('confidence_level'),
                data.get('radar_id', self.radar_id)
            ]
            
            self.worksheet.append_row(row)
            logger.debug(f'✅ Dados de contagem do {self.radar_id} enviados para Google Sheets!')
            return True
        except Exception as e:
            logger.error(f'❌ Erro ao enviar dados de contagem do {self.radar_id}: {str(e)}')
            logger.error(traceback.format_exc())
            return False

    def insert_summary_data(self, summary_data):
        """Inserir dados de resumo do contador"""
        try:
            # Verificar se existe planilha de resumo
            try:
                summary_worksheet = self.spreadsheet.worksheet('CounterSummary')
            except:
                summary_worksheet = self.spreadsheet.add_worksheet(title='CounterSummary', rows=100, cols=10)
                headers = ['date', 'session_duration', 'total_people', 'max_simultaneous', 
                          'avg_dwell_time', 'peak_hours', 'busiest_zone', 'radar_id']
                summary_worksheet.append_row(headers)
            
            row = [
                summary_data.get('date'),
                summary_data.get('session_duration'),
                summary_data.get('total_people'),
                summary_data.get('max_simultaneous'),
                summary_data.get('avg_dwell_time'),
                summary_data.get('peak_hours'),
                summary_data.get('busiest_zone'),
                summary_data.get('radar_id', self.radar_id)
            ]
            summary_worksheet.append_row(row)
            logger.info(f'✅ Resumo do contador {self.radar_id} enviado para Google Sheets!')
            return True
        except Exception as e:
            logger.error(f'❌ Erro ao enviar resumo do {self.radar_id}: {str(e)}')
            return False

def parse_serial_data(raw_data):
    """Função para parsear dados seriais do radar"""
    try:
        x_pattern = r'x_point\s*:\s*([-+]?\d*\.?\d+)'
        y_pattern = r'y_point\s*:\s*([-+]?\d*\.?\d+)'
        dop_pattern = r'dop_index\s*:\s*([-+]?\d+)'
        cluster_pattern = r'cluster_index\s*:\s*(\d+)'
        speed_pattern = r'move_speed\s*:\s*([-+]?\d*\.?\d+)\s*cm/s'
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
        distance_match = re.search(distance_pattern, raw_data, re.IGNORECASE)

        if x_match and y_match:
            data = {
                'x_point': float(x_match.group(1)),
                'y_point': float(y_match.group(1)),
                'dop_index': int(dop_match.group(1)) if dop_match else 0,
                'cluster_index': int(cluster_match.group(1)) if cluster_match else 0,
                'move_speed': float(speed_match.group(1))/100 if speed_match else 0.0,
                'distance': float(distance_match.group(1)) if distance_match else None
            }

            if data['distance'] is None:
                data['distance'] = math.sqrt(data['x_point']**2 + data['y_point']**2)
            
            return data
        else:
            return None
    except Exception as e:
        logger.error(f"❌ Erro ao analisar dados seriais: {str(e)}")
        return None

class TrackedPerson:
    def __init__(self, person_id, x, y, radar_id):
        self.person_id = person_id
        self.radar_id = radar_id
        self.x = x
        self.y = y
        self.entry_time = time.time()
        self.last_seen = time.time()
        self.positions = [(x, y, time.time())]
        self.zone_history = []
        self.is_active = True
        self.confidence = 1.0
        
    def update_position(self, x, y):
        self.x = x
        self.y = y
        self.last_seen = time.time()
        self.positions.append((x, y, time.time()))
        
        # Manter apenas as últimas 50 posições
        if len(self.positions) > 50:
            self.positions.pop(0)
    
    def get_duration_in_area(self):
        return self.last_seen - self.entry_time
    
    def get_average_speed(self):
        if len(self.positions) < 2:
            return 0.0
        
        speeds = []
        for i in range(1, len(self.positions)):
            prev_x, prev_y, prev_t = self.positions[i-1]
            curr_x, curr_y, curr_t = self.positions[i]
            
            distance = math.sqrt((curr_x - prev_x)**2 + (curr_y - prev_y)**2)
            time_diff = curr_t - prev_t
            
            if time_diff > 0:
                speed = distance / time_diff  # m/s
                speeds.append(speed)
        
        return np.mean(speeds) if speeds else 0.0

class ZoneManager:
    def __init__(self, radar_id):
        self.radar_id = radar_id
        
        # Zonas específicas por radar
        if radar_id == 'RADAR_1':  # Entrada
            self.INTEREST_ZONE_DISTANCE = 2.0  # Zona de entrada menor
            self.zones = {
                'ENTRADA': 'Zona de entrada principal',
                'PASSAGEM': 'Zona de passagem'
            }
        else:  # RADAR_2 - Interno
            self.INTEREST_ZONE_DISTANCE = 3.0  # Zona interna maior
            self.zones = {
                'INTERESSE': 'Zona de interesse interno',
                'CIRCULACAO': 'Zona de circulação'
            }
    
    def get_zone(self, x, y):
        """Determinar zona baseada na distância do radar"""
        distance = math.sqrt(x**2 + y**2)
        
        if self.radar_id == 'RADAR_1':
            if distance <= self.INTEREST_ZONE_DISTANCE:
                return 'ENTRADA'
            else:
                return 'PASSAGEM'
        else:  # RADAR_2
            if distance <= self.INTEREST_ZONE_DISTANCE:
                return 'INTERESSE'
            else:
                return 'CIRCULACAO'
    
    def get_distance(self, x, y):
        """Calcular distância do radar"""
        return math.sqrt(x**2 + y**2)

class PeopleCounterManager:
    def __init__(self, radar_id):
        self.radar_id = radar_id
        self.tracked_people = {}
        self.people_counter = 0
        self.total_entries = 0
        self.total_exits = 0
        self.max_simultaneous = 0
        self.session_start_time = time.time()
        self.session_id = str(uuid.uuid4())[:8]
        self.zone_manager = ZoneManager(radar_id)
        
        # Parâmetros de rastreamento
        self.POSITION_THRESHOLD = 0.8  # metros
        self.TIMEOUT_THRESHOLD = 5.0   # segundos
        self.MIN_CONFIDENCE = 0.5
        
        # Estatísticas por zona
        self.zone_stats = defaultdict(int)
        self.hourly_stats = defaultdict(int)

    def find_matching_person(self, x, y):
        """Encontrar pessoa existente baseada na proximidade"""
        best_match = None
        min_distance = self.POSITION_THRESHOLD
        
        for person_id, person in self.tracked_people.items():
            if not person.is_active:
                continue
                
            distance = math.sqrt((person.x - x)**2 + (person.y - y)**2)
            if distance < min_distance:
                min_distance = distance
                best_match = person_id
        
        return best_match

    def add_or_update_person(self, x, y):
        """Adicionar nova pessoa ou atualizar existente"""
        existing_id = self.find_matching_person(x, y)
        
        if existing_id:
            # Atualizar pessoa existente
            person = self.tracked_people[existing_id]
            person.update_position(x, y)
            person.confidence = min(1.0, person.confidence + 0.1)
            return existing_id
        else:
            # Criar nova pessoa
            person_id = f"{self.radar_id}_person_{len(self.tracked_people)}_{int(time.time())}"
            self.tracked_people[person_id] = TrackedPerson(person_id, x, y, self.radar_id)
            return person_id

    def cleanup_inactive_people(self):
        """Remover pessoas que não foram vistas recentemente"""
        current_time = time.time()
        to_remove = []
        
        for person_id, person in self.tracked_people.items():
            if current_time - person.last_seen > self.TIMEOUT_THRESHOLD:
                if person.is_active:
                    person.is_active = False
                    logger.debug(f"{self.radar_id}: Pessoa {person_id} marcada como inativa")
                
                # Remover após mais tempo para manter histórico
                if current_time - person.last_seen > self.TIMEOUT_THRESHOLD * 2:
                    to_remove.append(person_id)
        
        for person_id in to_remove:
            duration = self.tracked_people[person_id].get_duration_in_area()
            logger.debug(f"{self.radar_id}: Removendo pessoa {person_id} (duração: {duration:.1f}s)")
            del self.tracked_people[person_id]

    def get_current_count(self):
        """Contar pessoas ativas atualmente"""
        return sum(1 for person in self.tracked_people.values() if person.is_active)

    def check_entry_exit(self, person_id):
        """Verificar se houve entrada ou saída da zona de interesse"""
        person = self.tracked_people[person_id]
        current_zone = self.zone_manager.get_zone(person.x, person.y)
        current_distance = self.zone_manager.get_distance(person.x, person.y)
        
        # Verificar mudança de zona
        if person.zone_history:
            last_zone = person.zone_history[-1]
            if current_zone != last_zone:
                if self.radar_id == 'RADAR_1':  # Entrada
                    if last_zone == 'PASSAGEM' and current_zone == 'ENTRADA':
                        self.total_entries += 1
                        logger.info(f"🎯 {self.radar_id}: ENTRADA detectada - Pessoa {person_id} (distância: {current_distance:.2f}m)")
                        return 'ENTRY_ENTRANCE'
                    elif last_zone == 'ENTRADA' and current_zone == 'PASSAGEM':
                        self.total_exits += 1
                        logger.info(f"🚶 {self.radar_id}: SAÍDA detectada - Pessoa {person_id} (distância: {current_distance:.2f}m)")
                        return 'EXIT_ENTRANCE'
                else:  # RADAR_2 - Interno
                    if last_zone == 'CIRCULACAO' and current_zone == 'INTERESSE':
                        self.total_entries += 1
                        logger.info(f"🎯 {self.radar_id}: ENTRADA na zona de INTERESSE - Pessoa {person_id} (distância: {current_distance:.2f}m)")
                        return 'ENTRY_INTEREST'
                    elif last_zone == 'INTERESSE' and current_zone == 'CIRCULACAO':
                        self.total_exits += 1
                        logger.info(f"🚶 {self.radar_id}: SAÍDA da zona de INTERESSE - Pessoa {person_id} (distância: {current_distance:.2f}m)")
                        return 'EXIT_INTEREST'
        
        person.zone_history.append(current_zone)
        
        # Manter apenas as últimas 10 zonas
        if len(person.zone_history) > 10:
            person.zone_history.pop(0)
        
        return None

    def update_statistics(self):
        """Atualizar estatísticas gerais"""
        current_count = self.get_current_count()
        
        if current_count > self.max_simultaneous:
            self.max_simultaneous = current_count
        
        # Atualizar estatísticas por hora
        current_hour = datetime.now().hour
        self.hourly_stats[current_hour] = current_count
        
        # Atualizar estatísticas por zona
        for person in self.tracked_people.values():
            if person.is_active:
                zone = self.zone_manager.get_zone(person.x, person.y)
                self.zone_stats[zone] += 1

    def get_summary_statistics(self):
        """Obter estatísticas resumidas"""
        session_duration = time.time() - self.session_start_time
        total_people = len(self.tracked_people)
        
        avg_dwell_time = 0
        if self.tracked_people:
            durations = [p.get_duration_in_area() for p in self.tracked_people.values()]
            avg_dwell_time = np.mean(durations)
        
        busiest_zone = max(self.zone_stats, key=self.zone_stats.get) if self.zone_stats else 'NONE'
        peak_hour = max(self.hourly_stats, key=self.hourly_stats.get) if self.hourly_stats else 0
        
        return {
            'date': datetime.now().strftime('%Y-%m-%d'),
            'session_duration': round(session_duration, 2),
            'total_people': total_people,
            'max_simultaneous': self.max_simultaneous,
            'avg_dwell_time': round(avg_dwell_time, 2),
            'peak_hours': f"{peak_hour}:00",
            'busiest_zone': busiest_zone,
            'radar_id': self.radar_id
        }

class RadarCounterManager:
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
        self.people_counter = PeopleCounterManager(self.radar_id)
        
        # Controle de output
        self.last_output_time = time.time()
        self.OUTPUT_INTERVAL = 10  # 10 segundos entre outputs

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
        
        # Enviar resumo final
        if self.gsheets_manager:
            summary = self.people_counter.get_summary_statistics()
            self.gsheets_manager.insert_summary_data(summary)
        
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
                            if not line or not line.startswith('{'):
                                continue
                            try:
                                data_json = json.loads(line)
                                radar_id = data_json.get("radar_id", self.radar_id)
                                max_interesse = data_json.get("max_interesse", 0)
                                max_passagem = data_json.get("max_passagem", 0)
                                max_total = data_json.get("max_total", 0)
                                timestamp = data_json.get("timestamp", 0)
                                samples = data_json.get("samples", 0)
                                detections = data_json.get("detections", [])
                                if detections:
                                    for det in detections:
                                        x = det.get("x", "")
                                        y = det.get("y", "")
                                        zona = det.get("zona", "")
                                        row = [radar_id, max_interesse, max_passagem, max_total, timestamp, samples, x, y, zona]
                                        if self.gsheets_manager:
                                            self.gsheets_manager.worksheet.append_row(row)
                                else:
                                    # Se não houver detecções, salva linha com x, y, zona vazios
                                    row = [radar_id, max_interesse, max_passagem, max_total, timestamp, samples, "", "", ""]
                                    if self.gsheets_manager:
                                        self.gsheets_manager.worksheet.append_row(row)
                            except Exception as e:
                                logger.error(f"Erro ao processar linha JSON: {e}")
                time.sleep(0.01)
            except Exception as e:
                logger.error(f"{self.color} {self.radar_name}: ❌ Erro no loop: {str(e)}")
                time.sleep(1)

    def process_counter_data(self, raw_data):
        """Processa os dados do contador de pessoas"""
        try:
            data = parse_serial_data(raw_data)
            if not data:
                return

            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            # Adicionar ou atualizar pessoa
            person_id = self.people_counter.add_or_update_person(
                data['x_point'], data['y_point']
            )
            
            # Verificar entrada/saída
            event_type = self.people_counter.check_entry_exit(person_id)
            
            # Preparar dados para a planilha
            if self.gsheets_manager:
                distance = self.people_counter.zone_manager.get_distance(data['x_point'], data['y_point'])
                counter_data = {
                    'timestamp': timestamp,
                    'session_id': self.people_counter.session_id,
                    'event_type': event_type or 'UPDATE',
                    'current_count': self.people_counter.get_current_count(),
                    'total_entries': self.people_counter.total_entries,
                    'total_exits': self.people_counter.total_exits,
                    'max_simultaneous': self.people_counter.max_simultaneous,
                    'person_id': person_id,
                    'x_position': data['x_point'],
                    'y_position': data['y_point'],
                    'distance': distance,
                    'zone': self.people_counter.zone_manager.get_zone(data['x_point'], data['y_point']),
                    'duration_in_area': self.people_counter.tracked_people[person_id].get_duration_in_area(),
                    'speed': self.people_counter.tracked_people[person_id].get_average_speed(),
                    'confidence_level': self.people_counter.tracked_people[person_id].confidence,
                    'radar_id': self.radar_id
                }
                
                success = self.gsheets_manager.insert_counter_data(counter_data)
                if not success:
                    logger.error(f"{self.color} {self.radar_name}: ❌ Falha ao enviar para Sheets")
            
        except Exception as e:
            logger.error(f"{self.color} {self.radar_name}: ❌ Erro ao processar dados: {str(e)}")

    def output_statistics(self):
        """Exibir estatísticas atuais do contador"""
        current_count = self.people_counter.get_current_count()
        
        # Contar pessoas por zona
        zone_counts = defaultdict(int)
        for person in self.people_counter.tracked_people.values():
            if person.is_active:
                zone = self.people_counter.zone_manager.get_zone(person.x, person.y)
                zone_counts[zone] += 1
        
        if self.radar_id == 'RADAR_1':
            zone1_name = "ENTRADA"
            zone2_name = "PASSAGEM"
        else:
            zone1_name = "INTERESSE"
            zone2_name = "CIRCULACAO"
        
        output = [
            f"\n{self.color} ═══ {self.radar_name.upper()} ═══",
            f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"📊 Sessão: {self.people_counter.session_id}",
            "-" * 50,
            f"👤 Pessoas Ativas: {current_count}",
            f"🎯 Zona {zone1_name}: {zone_counts[zone1_name]} pessoas",
            f"🚶 Zona {zone2_name}: {zone_counts[zone2_name]} pessoas",
            f"🎯 Máximo Simultâneo: {self.people_counter.max_simultaneous}",
            f"🎯 Total Entradas: {self.people_counter.total_entries}",
            f"🚶 Total Saídas: {self.people_counter.total_exits}",
            f"⏱️ Duração da Sessão: {time.time() - self.people_counter.session_start_time:.0f}s",
            "═" * 50
        ]
        
        logger.info("\n".join(output))

class EstandeCounterSystem:
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
        """Inicializa o sistema dual radar counter"""
        logger.info("🚀 Inicializando Sistema Dual Contador de Pessoas...")
        
        # Detecta portas disponíveis
        if not self.detect_available_ports():
            return False
        
        # Inicializa Google Sheets para cada radar usando IDs específicos
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
        
        # Inicializa radares
        for config in RADAR_CONFIGS:
            radar = RadarCounterManager(config)
            self.radars.append(radar)
        
        return True

    def start(self):
        """Inicia todos os radares"""
        logger.info("🚀 Iniciando contagem de pessoas do estande...")
        
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
        
        logger.info("🎯 Sistema de contagem de pessoas ativo!")
        return True

    def stop(self):
        """Para todos os radares"""
        logger.info("🛑 Parando contagem de pessoas...")
        
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
                'description': radar.description,
                'current_count': radar.people_counter.get_current_count() if radar.is_running else 0,
                'total_entries': radar.people_counter.total_entries if radar.is_running else 0
            }
            status['radars'].append(radar_status)
        
        return status

def main():
    """Função principal"""
    counter_system = EstandeCounterSystem()
    
    try:
        # Inicializa o sistema
        if not counter_system.initialize():
            logger.error("❌ Falha na inicialização do sistema")
            return
        
        # Inicia os radares
        if not counter_system.start():
            logger.error("❌ Falha ao iniciar os radares") 
            return
        
        # Exibe status
        status = counter_system.get_status()
        logger.info("=" * 70)
        logger.info("👥 SISTEMA CONTADOR DE PESSOAS - ESTANDE ATIVO")
        logger.info("=" * 70)
        for radar_status in status['radars']:
            status_icon = "🟢" if radar_status['running'] else "🔴"
            logger.info(f"{status_icon} {radar_status['name']}: {radar_status['port']}")
            logger.info(f"    📋 {radar_status['description']}")
        logger.info("⚡ Pressione Ctrl+C para encerrar")
        logger.info("=" * 70)
        
        # Mantém o sistema rodando
        while True:
            time.sleep(5)
            
            # Status rápido a cada 30 segundos
            if int(time.time()) % 30 == 0:
                current_status = counter_system.get_status()
                total_people = sum(r['current_count'] for r in current_status['radars'])
                total_entries = sum(r['total_entries'] for r in current_status['radars'])
                
                if current_status['running_radars'] != current_status['total_radars']:
                    logger.warning(f"⚠️ Apenas {current_status['running_radars']}/{current_status['total_radars']} radares ativos")
                else:
                    logger.info(f"📊 RESUMO: {total_people} pessoas ativas | {total_entries} entradas totais")
    
    except KeyboardInterrupt:
        logger.info("🛑 Encerrando por solicitação do usuário...")
    
    except Exception as e:
        logger.error(f"❌ Erro inesperado: {str(e)}")
        logger.error(traceback.format_exc())
    
    finally:
        counter_system.stop()

if __name__ == "__main__":
    main() 
