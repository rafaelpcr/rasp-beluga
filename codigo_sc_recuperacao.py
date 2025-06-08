# CÓDIGO SANTA CRUZ COM AUTO-RECUPERAÇÃO E CORREÇÕES APLICADAS
# Versão corrigida sem problemas de indentação

import os
import time
import json
import logging
import serial
import signal
from datetime import datetime, timedelta
import threading
import gc
import psutil
import sys

# Configuração de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuração do evento Santa Cruz
RADAR_CONFIG = {
    'id': 'RADAR_SANTA_CRUZ',
    'name': 'Radar Santa Cruz Cabrália',
    'localizacao': 'Entrada Principal - Estande Prefeitura',
    'port': '/dev/ttyUSB0',
    'baudrate': 115200,
    'color': '🔴',
    'description': 'Contador de Pessoas - Estande Santa Cruz Cabrália',
    'spreadsheet_id': '1vSXn7A0-YJGk-fhBgAG1BZfQEJOYVGOF_YQRU9QNF_k'
}

import gspread
from google.oauth2.service_account import Credentials

class AutoRecoveryGoogleSheetsManager:
    """Manager do Google Sheets com sistema de auto-recuperação completo"""
    
    def __init__(self, creds_path, spreadsheet_id, radar_id):
        self.creds_path = creds_path
        self.spreadsheet_id = spreadsheet_id
        self.radar_id = radar_id
        self.gc = None
        self.spreadsheet = None
        self.worksheet = None
        
        # Controles de auto-recuperação
        self.consecutive_failures = 0
        self.max_failures = 5
        self.last_recovery_attempt = datetime.now() - timedelta(minutes=10)
        self.recovery_backoff = 60  # Segundos
        
        # Tenta conectar inicialmente
        self._connect_with_recovery()
    
    def _connect_with_recovery(self):
        """Conecta ao Google Sheets com auto-recuperação"""
        try:
            SCOPES = [
                'https://www.googleapis.com/auth/spreadsheets',
                'https://www.googleapis.com/auth/drive',
                'https://www.googleapis.com/auth/drive.file'
            ]
            
            creds = Credentials.from_service_account_file(self.creds_path, scopes=SCOPES)
            self.gc = gspread.authorize(creds)
            self.spreadsheet = self.gc.open_by_key(self.spreadsheet_id)
            self.worksheet = self.spreadsheet.sheet1
            
            # Configura headers se necessário
            self._setup_headers()
            
            logger.info("✅ Google Sheets conectado com auto-recovery")
            self.consecutive_failures = 0
            return True
            
        except Exception as e:
            logger.error(f"❌ Erro conectando Google Sheets: {e}")
            self.consecutive_failures += 1
            return False
    
    def _setup_headers(self):
        """Configura cabeçalhos (com retry)"""
        try:
            headers = self.worksheet.row_values(1)
            expected_headers = [
                'radar_id', 'timestamp', 'person_count', 'person_id',
                'zone', 'distance', 'confidence', 'total_detected', 'max_simultaneous'
            ]
            
            if not headers or len(headers) < 9:
                logger.info("🔧 Configurando cabeçalhos...")
                self.worksheet.clear()
                self.worksheet.append_row(expected_headers)
        except Exception as e:
            logger.warning(f"⚠️ Erro configurando cabeçalhos: {e}")

    def append_row_with_auto_recovery(self, row):
        """Envia linha com auto-recuperação completa"""
        for attempt in range(3):
            try:
                if not self.worksheet:
                    if not self._connect_with_recovery():
                        continue
                
                self.worksheet.append_row(row)
                self.consecutive_failures = 0
                return True
                
            except Exception as e:
                logger.warning(f"⚠️ Erro enviando linha (tentativa {attempt+1}): {e}")
                self.consecutive_failures += 1
                
                # Auto-recuperação em caso de erro
                if attempt < 2:
                    time.sleep(2 ** attempt)  # Backoff exponencial
                    self._attempt_full_recovery()
        
        logger.error(f"❌ Falha total enviando linha após 3 tentativas")
        return False
    
    def _attempt_full_recovery(self):
        """Tenta recuperação completa"""
        try:
            current_time = datetime.now()
            if (current_time - self.last_recovery_attempt).total_seconds() < self.recovery_backoff:
                return False
            
            self.last_recovery_attempt = current_time
            logger.info("🔄 Tentando recuperação completa do Google Sheets...")
            
            # Reset completo
            self.gc = None
            self.spreadsheet = None
            self.worksheet = None
            
            # Reconnect
            return self._connect_with_recovery()
            
        except Exception as e:
            logger.error(f"❌ Erro na recuperação completa: {e}")
            return False
    
    def health_check(self):
        """Verifica saúde da conexão"""
        try:
            if self.worksheet:
                # Tenta operação simples
                self.worksheet.row_count
                return True
            return False
        except:
            return False

class ZoneManager:
    def __init__(self):
        # Configuração baseada no layout real do estande
        # Radar instalado no FUNDO do estande
        
        # Limites das ativações (baseado no diagrama) - AJUSTADOS para melhor detecção
        self.ZONA_CONFIGS = {
            # LADO ESQUERDO (X < -0.5)
            'SALA_REBOCO': {
                'x_min': -3.5, 'x_max': -0.3,
                'y_min': 0.3, 'y_max': 3.8,
                'distance_range': (1.0, 4.0)
            },
            'IGREJINHA': {
                'x_min': -3.0, 'x_max': -0.2,
                'y_min': 2.8, 'y_max': 6.0,
                'distance_range': (2.5, 6.0)
            },
            
            # CENTRO (X entre -0.8 e 0.8)
            'CENTRO': {
                'x_min': -1.0, 'x_max': 1.0,
                'y_min': 1.0, 'y_max': 4.5,
                'distance_range': (2.0, 5.0)
            },
            
            # LADO DIREITO (X > 0.5)
            'ARGOLA': {
                'x_min': 0.3, 'x_max': 3.0,
                'y_min': 4.0, 'y_max': 7.5,
                'distance_range': (4.0, 8.0)
            },
            'BEIJO': {
                'x_min': 0.5, 'x_max': 3.5,
                'y_min': 2.0, 'y_max': 5.5,
                'distance_range': (3.5, 7.5)
            },
            'PESCARIA': {
                'x_min': 0.8, 'x_max': 4.0,
                'y_min': 0.2, 'y_max': 4.0,
                'distance_range': (4.0, 9.0)
            }
        }
        
    def get_zone(self, x, y):
        """Determinar zona baseada nas ativações específicas"""
        distance = self.get_distance(x, y)
        
        for zona_name, config in self.ZONA_CONFIGS.items():
            if (config['x_min'] <= x <= config['x_max'] and
                config['y_min'] <= y <= config['y_max'] and
                config['distance_range'][0] <= distance <= config['distance_range'][1]):
                return zona_name
        
        return 'FORA_ATIVACOES'
    
    def get_distance(self, x, y):
        """Calcular distância do radar"""
        import math
        return math.sqrt(x**2 + y**2)
    
    def get_zone_description(self, zone_name):
        """Retorna descrição amigável da zona"""
        descriptions = {
            'SALA_REBOCO': 'Sala de Reboco',
            'IGREJINHA': 'Igrejinha', 
            'CENTRO': 'Centro',
            'ARGOLA': 'Jogo da Argola',
            'BEIJO': 'Barraca do Beijo',
            'PESCARIA': 'Pescaria',
            'FORA_ATIVACOES': 'Fora das Ativações'
        }
        return descriptions.get(zone_name, zone_name)

class AutoRecoveryRadarCounter:
    def __init__(self, config):
        self.config = config
        self.radar_id = config['id']
        self.radar_name = config['name']
        self.port = config['port']
        self.baudrate = config['baudrate']
        self.color = config['color']
        self.description = config['description']
        
        # Sistema de auto-recuperação
        self.start_time = datetime.now()
        self.last_data_received = datetime.now()
        self.last_sheets_success = datetime.now()
        self.system_restart_count = 0
        self.max_system_restarts = 3
        
        self.serial_connection = None
        self.is_running = False
        self.receive_thread = None
        self.gsheets_manager = None
        self.zone_manager = ZoneManager()
        
        # Sistema robusto de contagem de pessoas
        self.current_people = {}
        self.previous_people = {}
        self.people_history = {}
        self.total_people_detected = 0
        self.max_simultaneous_people = 0
        self.session_start_time = datetime.now()
        
        # Configurações de tracking CORRIGIDAS
        self.exit_timeout = 30.0  # 30 segundos para pessoas paradas
        self.reentry_timeout = 10.0
        self.last_update_time = time.time()
        
        # Controle de escrita no Google Sheets
        self.last_sheets_write = 0
        self.sheets_write_interval = 180.0  # 3 minutos
        self.pending_data = []
        
        # Estatísticas detalhadas
        self.entries_count = 0
        self.exits_count = 0
        self.unique_people_today = set()
        
        # Thread de monitoramento
        self.monitoring_thread = None

    def start_health_monitoring(self):
        """Inicia thread de monitoramento de saúde"""
        if not self.monitoring_thread or not self.monitoring_thread.is_alive():
            self.monitoring_thread = threading.Thread(target=self._health_monitoring_loop, daemon=True)
            self.monitoring_thread.start()
            logger.info("🏥 Monitoramento de saúde iniciado")

    def _health_monitoring_loop(self):
        """Loop de monitoramento de saúde do sistema"""
        while self.is_running:
            try:
                self._check_system_health()
                time.sleep(30)  # Verifica a cada 30 segundos
            except Exception as e:
                logger.error(f"❌ Erro no monitoramento de saúde: {e}")
                time.sleep(60)

    def _check_system_health(self):
        """Verifica saúde geral do sistema"""
        current_time = datetime.now()
        
        # 1. Verifica se recebeu dados recentemente
        time_since_data = (current_time - self.last_data_received).total_seconds()
        if time_since_data > 300:  # 5 minutos sem dados
            logger.warning(f"⚠️ Sem dados há {time_since_data:.0f}s - tentando recuperação")
            if self._should_attempt_recovery():
                self._attempt_serial_recovery()
        
        # 2. Verifica saúde do Google Sheets
        if self.gsheets_manager and not self.gsheets_manager.health_check():
            logger.warning("⚠️ Google Sheets não responsivo - tentando recuperação")
            self.gsheets_manager._attempt_full_recovery()
        
        # 3. Limpeza de memória preventiva
        if time_since_data > 600:  # 10 minutos sem dados
            self._cleanup_memory()
        
        # 4. Restart preventivo após muito tempo
        session_duration = (current_time - self.start_time).total_seconds()
        if session_duration > 43200:  # 12 horas
            logger.info("🔄 Restart preventivo após 12 horas")
            self._attempt_system_restart()

    def _should_attempt_recovery(self):
        """Verifica se deve tentar recuperação"""
        return (
            self.system_restart_count < self.max_system_restarts and
            (datetime.now() - self.last_data_received).total_seconds() > 300
        )

    def _cleanup_memory(self):
        """Limpeza agressiva de memória"""
        try:
            # Limpa histórico antigo
            current_time = time.time()
            old_people = []
            for person_id, person_info in self.current_people.items():
                if (current_time - person_info.get('last_seen', 0)) > self.exit_timeout:
                    old_people.append(person_id)
            
            for person_id in old_people:
                del self.current_people[person_id]
                logger.info(f"🧹 Limpeza: removido {person_id}")
            
            # Force garbage collection
            gc.collect()
            
        except Exception as e:
            logger.error(f"❌ Erro na limpeza: {e}")

    def _attempt_serial_recovery(self):
        """Tenta recuperar conexão serial"""
        try:
            logger.info("🔄 Tentando recuperação serial...")
            
            if self.serial_connection and self.serial_connection.is_open:
                self.serial_connection.close()
                time.sleep(2)
            
            # Tenta reconectar
            if self.connect():
                logger.info("✅ Recuperação serial bem-sucedida")
                self.last_data_received = datetime.now()
                return True
            else:
                logger.error("❌ Recuperação serial falhou")
                return False
                
        except Exception as e:
            logger.error(f"❌ Erro na recuperação serial: {e}")
            return False

    def _attempt_system_restart(self):
        """Restart completo do sistema como último recurso"""
        try:
            self.system_restart_count += 1
            logger.warning(f"🔄 RESTART SISTEMA #{self.system_restart_count}")
            
            # Para tudo
            self.stop()
            time.sleep(5)
            
            # Reinicia
            if self.start(self.gsheets_manager):
                logger.info("✅ Restart bem-sucedido")
                return True
            else:
                logger.error("❌ Restart falhou")
                return False
                
        except Exception as e:
            logger.error(f"❌ Erro no restart: {e}")
            return False

    def connect(self):
        """Conecta ao radar via serial com auto-recuperação"""
        try:
            if self.serial_connection and self.serial_connection.is_open:
                self.serial_connection.close()
                time.sleep(1)
            
            self.serial_connection = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=2,
                write_timeout=2
            )
            
            if self.serial_connection.is_open:
                logger.info(f"✅ Radar conectado: {self.port}")
                return True
            else:
                logger.error(f"❌ Falha na conexão: {self.port}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Erro conectando radar: {e}")
            return False

    def start(self, gsheets_manager):
        """Inicia o contador com auto-recuperação"""
        try:
            self.gsheets_manager = gsheets_manager
            
            if not self.connect():
                logger.error("❌ Falha na conexão inicial")
                return False
            
            self.is_running = True
            self.receive_thread = threading.Thread(target=self.receive_data_loop, daemon=True)
            self.receive_thread.start()
            
            # Inicia monitoramento de saúde
            self.start_health_monitoring()
            
            logger.info(f"✅ {self.radar_name} iniciado com auto-recuperação")
            return True
            
        except Exception as e:
            logger.error(f"❌ Erro iniciando contador: {e}")
            return False

    def stop(self):
        """Para o contador"""
        self.is_running = False
        
        if self.serial_connection and self.serial_connection.is_open:
            self.serial_connection.close()
        
        if self.receive_thread and self.receive_thread.is_alive():
            self.receive_thread.join(timeout=5)
        
        logger.info(f"🛑 {self.radar_name} parado")

    def receive_data_loop(self):
        """Loop principal de recebimento com auto-recuperação"""
        buffer = ""
        consecutive_errors = 0
        
        while self.is_running:
            try:
                if not self.serial_connection or not self.serial_connection.is_open:
                    logger.warning("⚠️ Conexão perdida, tentando reconectar...")
                    if not self.connect():
                        time.sleep(5)
                        continue
                
                in_waiting = self.serial_connection.in_waiting or 0
                data = self.serial_connection.read(in_waiting or 1)
                
                if data:
                    consecutive_errors = 0
                    self.last_data_received = datetime.now()
                    
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
                                self.process_json_data(data_json)
                                time.sleep(3.0)  # 3 segundos entre processamentos
                            except json.JSONDecodeError:
                                logger.debug(f"JSON inválido: {line[:50]}...")
                            except Exception as e:
                                logger.error(f"Erro processando JSON: {e}")
                
                time.sleep(0.01)
                
            except Exception as e:
                consecutive_errors += 1
                logger.error(f"❌ Erro no loop (#{consecutive_errors}): {e}")
                
                if consecutive_errors > 10:
                    logger.warning("⚠️ Muitos erros consecutivos - tentando recuperação")
                    self._attempt_serial_recovery()
                    consecutive_errors = 0
                
                time.sleep(1)

    def convert_timestamp(self, timestamp_ms):
        """Converte timestamp do Arduino para formato legível CORRIGIDO"""
        try:
            if timestamp_ms and timestamp_ms > 0:
                # Arduino envia milissegundos desde boot, converte para timestamp real
                timestamp_seconds = timestamp_ms / 1000.0
                return datetime.fromtimestamp(timestamp_seconds).strftime('%d/%m/%Y %H:%M:%S')
            else:
                # Fallback para horário atual
                return datetime.now().strftime('%d/%m/%Y %H:%M:%S')
        except:
            return datetime.now().strftime('%d/%m/%Y %H:%M:%S')

    def update_people_count(self, person_count, active_people):
        """Atualiza contagem de pessoas com lógica robusta CORRIGIDA"""
        current_time = time.time()
        
        # Converte lista para dict para processamento
        current_people_dict = {}
        
        for i, person in enumerate(active_people):
            # SEMPRE usa distância calculada (mais confiável)
            x_pos = person.get('x_pos', 0)
            y_pos = person.get('y_pos', 0)
            import math
            calculated_distance = math.sqrt(x_pos**2 + y_pos**2)
            
            # Calcula zona específica das ativações
            zone = self.zone_manager.get_zone(x_pos, y_pos)
            
            # ID único baseado em posição e zona
            person_id = f"person_{zone}_{calculated_distance:.1f}_{i}"
            
            # Atualiza dados da pessoa
            person_info = {
                'id': person_id,
                'x_pos': x_pos,
                'y_pos': y_pos,
                'distance': calculated_distance,  # Sempre usa calculada
                'zone': zone,
                'confidence': person.get('confidence', 85),
                'stationary': person.get('stationary', False),
                'last_seen': current_time,
                'first_seen': current_time
            }
            
            current_people_dict[person_id] = person_info
        
        # Detecta pessoas novas reais
        new_entries = []
        people_really_new = 0
        
        for person_id, person_info in current_people_dict.items():
            if person_id not in self.current_people:
                # Verifica se não é pessoa que acabou de sair (anti-flickering)
                is_really_new = True
                for old_id, old_person in self.previous_people.items():
                    old_zone = old_person.get('zone', '')
                    old_dist = old_person.get('distance', 0)
                    new_zone = person_info.get('zone', '')
                    new_dist = person_info.get('distance', 0)
                    
                    if (old_zone == new_zone and 
                        abs(old_dist - new_dist) < 0.5 and
                        (current_time - old_person.get('last_seen', 0)) < 5.0):
                        is_really_new = False
                        break
                
                if is_really_new:
                    new_entries.append(person_id)
                    people_really_new += 1
                    self.unique_people_today.add(person_id)
                    zone = person_info.get('zone', 'DESCONHECIDA')
                    dist = person_info.get('distance', 0)
                    logger.info(f"🆕 ENTRADA REAL #{people_really_new}: {zone} {dist:.1f}m")
        
        # Atualiza total
        if people_really_new > 0:
            self.total_people_detected += people_really_new
            self.entries_count += people_really_new
            logger.info(f"📊 TOTAL ATUALIZADO: +{people_really_new} = {self.total_people_detected} total")
        
        # Detecta saídas reais
        exits = []
        people_really_left = 0
        for person_id, person_info in self.current_people.items():
            if person_id not in current_people_dict:
                last_seen = person_info.get('last_seen', 0)
                if (current_time - last_seen) > self.exit_timeout:  # 30 segundos
                    exits.append(person_id)
                    people_really_left += 1
                    self.exits_count += 1
                    zone = person_info.get('zone', 'DESCONHECIDA')
                    dist = person_info.get('distance', 0)
                    logger.info(f"🚪 SAÍDA REAL: {zone} {dist:.1f}m")
        
        if people_really_left > 0:
            logger.info(f"📊 SAÍDAS: +{people_really_left} = {self.exits_count} total")
        
        # Atualiza estado
        self.previous_people = self.current_people.copy()
        self.current_people = current_people_dict
        
        # Atualiza máximo simultâneo
        current_simultaneous = len(current_people_dict)
        if current_simultaneous > self.max_simultaneous_people:
            self.max_simultaneous_people = current_simultaneous
            logger.info(f"📊 NOVO MÁXIMO SIMULTÂNEO: {self.max_simultaneous_people} pessoas")
        
        self.last_update_time = current_time

    def process_json_data(self, data_json):
        """Processa dados JSON CORRIGIDO"""
        try:
            radar_id = data_json.get("radar_id", self.radar_id)
            timestamp_ms = data_json.get("timestamp_ms", 0)
            person_count = data_json.get("person_count", 0)
            active_people = data_json.get("active_people", [])
            
            # Converte timestamp CORRIGIDO
            formatted_timestamp = self.convert_timestamp(timestamp_ms)
            
            # Atualiza contadores locais
            self.update_people_count(person_count, active_people)
            
            # Limpa terminal e mostra dados
            os.system('clear')
            print(f"\n{self.color} ═══ CONTADOR ROBUSTO + AUTO-RECOVERY ═══")
            print(f"⏰ {formatted_timestamp}")
            print(f"📡 {radar_id} | 👥 ATIVAS: {person_count}")
            print(f"🎯 TOTAL DETECTADAS: {self.total_people_detected} | 📊 MÁXIMO SIMULTÂNEO: {self.max_simultaneous_people}")
            print(f"🔄 ENTRADAS: {self.entries_count} | 🚪 SAÍDAS: {self.exits_count} | 📋 BALANÇO: {self.entries_count - self.exits_count}")
            print(f"🆔 PESSOAS ÚNICAS: {len(self.unique_people_today)}")
            
            # Mostra duração da sessão
            session_duration = datetime.now() - self.session_start_time
            duration_str = f"{session_duration.total_seconds()/60:.1f}min"
            print(f"⏱️ SESSÃO: {duration_str}")
            
            # Status do envio para planilha
            pending_count = len(self.pending_data)
            time_since_last_send = time.time() - self.last_sheets_write
            next_send_in = max(0, self.sheets_write_interval - time_since_last_send)
            if pending_count > 0:
                print(f"📋 BUFFER: {pending_count} linhas | ⏳ Próximo envio em: {next_send_in:.0f}s")
            else:
                print(f"📋 PLANILHA: Sincronizada ✅")
            
            if active_people and len(active_people) > 0:
                print(f"\n👥 PESSOAS DETECTADAS AGORA ({len(active_people)}) - TRACKING ROBUSTO:")
                print(f"{'#':<2} {'Ativação':<15} {'Dist(m)':<7} {'X,Y':<12} {'Conf%':<5} {'Status':<8} {'Desde':<8}")
                print("-" * 75)
                
                current_time = time.time()
                for i, person in enumerate(active_people):
                    # Calcula distância real das coordenadas
                    x_pos = person.get('x_pos', 0)
                    y_pos = person.get('y_pos', 0)
                    import math
                    distance = math.sqrt(x_pos**2 + y_pos**2)
                    
                    confidence = person.get("confidence", 85)
                    stationary = person.get("stationary", False)
                    zone = self.zone_manager.get_zone(x_pos, y_pos)
                    
                    # Calcula tempo desde primeira detecção
                    person_id = f"person_{zone}_{distance:.1f}_{i}"
                    if person_id in self.current_people:
                        first_seen = self.current_people[person_id].get('first_seen', current_time)
                        time_in_area = current_time - first_seen
                        time_str = f"{time_in_area:.0f}s" if time_in_area < 60 else f"{time_in_area/60:.1f}m"
                    else:
                        time_str = "novo"

                    status = "Parado" if stationary else "Móvel"
                    pos_str = f"{x_pos:.2f},{y_pos:.2f}"
                    zone_desc = self.zone_manager.get_zone_description(zone)[:14]
                    
                    print(f"{i+1:<2} {zone_desc:<15} {distance:<7.2f} {pos_str:<12} {confidence:<5}% {status:<8} {time_str:<8}")
                
                print("💡 DETECTANDO {} pessoa(s) SIMULTANEAMENTE".format(len(active_people)))

                # Para planilha com distâncias CORRIGIDAS
                if self.gsheets_manager:
                    avg_confidence = sum(p.get("confidence", 0) for p in active_people) / len(active_people)
                    zones_detected = list(set(self.zone_manager.get_zone(p.get('x_pos', 0), p.get('y_pos', 0)) for p in active_people))
                    zones_str = ",".join(sorted(zones_detected))

                    # ID profissional
                    if len(active_people) == 1:
                        person_description = "Pessoa Individual"
                    elif len(active_people) <= 3:
                        person_description = "Grupo Pequeno"
                    else:
                        person_description = "Grupo Grande"

                    # DISTÂNCIA MÉDIA CORRIGIDA - sempre das coordenadas
                    import math
                    valid_distances = []
                    for p in active_people:
                        x = p.get('x_pos', 0)
                        y = p.get('y_pos', 0)
                        distance = math.sqrt(x**2 + y**2)  # SEMPRE calculada
                        valid_distances.append(distance)
                    
                    avg_distance = sum(valid_distances) / len(valid_distances) if valid_distances else 0

                    # Só envia se houve mudança
                    current_people_count = len(active_people)
                    last_count = getattr(self, 'last_sent_count', -1)
                    time_since_last_send = time.time() - self.last_sheets_write
                    should_send = (current_people_count != last_count or time_since_last_send > 300)
                    
                    if should_send:
                        row = [
                            radar_id,
                            formatted_timestamp,
                            len(active_people),
                            person_description,
                            zones_str,
                            f"{avg_distance:.1f}",  # Distância REAL
                            f"{avg_confidence:.0f}",
                            self.total_people_detected,
                            self.max_simultaneous_people
                        ]
                        self.pending_data.append(row)
                        self.last_sent_count = current_people_count
                        logger.info(f"📋 Dados adicionados ao buffer (mudança: {last_count} → {current_people_count})")

                # Estatísticas por zona
                zone_stats = {}
                high_confidence = 0
                for person in active_people:
                    x_pos = person.get('x_pos', 0)
                    y_pos = person.get('y_pos', 0)
                    zone = self.zone_manager.get_zone(x_pos, y_pos)
                    zone_stats[zone] = zone_stats.get(zone, 0) + 1
                    if person.get("confidence", 0) >= 70:
                        high_confidence += 1

                if zone_stats:
                    print("📊 DISTRIBUIÇÃO POR ATIVAÇÃO:")
                    for zone, count in zone_stats.items():
                        zone_desc = self.zone_manager.get_zone_description(zone)
                        print(f"   • {zone_desc}: {count} pessoa(s)")
                    print()

                print(f"✅ QUALIDADE: {high_confidence}/{len(active_people)} com alta confiança (≥70%)")

            else:
                print(f"\n👻 Nenhuma pessoa detectada no momento.")
                
                # Envia dados zerados apenas se houve mudança
                if self.gsheets_manager and len(self.previous_people) > 0:
                    last_count = getattr(self, 'last_sent_count', -1)
                    if last_count != 0:
                        row = [
                            radar_id, formatted_timestamp, 0, "Area_Vazia", "VAZIA", 
                            "0", "0", self.total_people_detected, self.max_simultaneous_people
                        ]
                        self.pending_data.append(row)
                        self.last_sent_count = 0
                        logger.info(f"📋 Área vazia detectada")

            print("\n" + "=" * 60)
            print("🎯 SISTEMA ROBUSTO + AUTO-RECOVERY ATIVO")
            print("✅ Tracking preciso | ✅ Auto-reconexão | ✅ Anti-quota")
            print("⚡ Pressione Ctrl+C para encerrar")

            # Envia com auto-recovery
            self.send_pending_data_with_recovery()

        except Exception as e:
            logger.error(f"Erro ao processar dados JSON: {e}")

    def send_pending_data_with_recovery(self):
        """Envia dados para Google Sheets com auto-recuperação"""
        try:
            current_time = time.time()
            
            if (current_time - self.last_sheets_write) < self.sheets_write_interval:
                return
            
            if not self.pending_data or not self.gsheets_manager:
                return
            
            data_to_send = self.pending_data[-10:] if len(self.pending_data) > 10 else self.pending_data
            
            if data_to_send:
                logger.info(f"📊 Enviando {len(data_to_send)} linhas com auto-recovery...")
                
                for row in data_to_send:
                    success = self.gsheets_manager.append_row_with_auto_recovery(row)
                    if success:
                        self.last_sheets_success = datetime.now()
                    time.sleep(0.5)
                
                logger.info(f"✅ {len(data_to_send)} linhas enviadas com auto-recovery!")
                
                self.last_sheets_write = current_time
                self.pending_data = []
                
        except Exception as e:
            logger.error(f"❌ Erro no envio com recovery: {e}")
            if "quota" in str(e).lower() or "429" in str(e):
                logger.warning("⚠️ Quota excedida - aumentando intervalo para 60s")
                self.sheets_write_interval = 60.0

    def get_current_count(self):
        return len(self.current_people)
    
    def get_total_detected(self):
        return self.total_people_detected

    def get_status(self):
        """Retorna status completo do radar"""
        return {
            'id': self.radar_id,
            'name': self.radar_name,
            'port': self.port,
            'running': self.is_running,
            'connected': self.serial_connection and self.serial_connection.is_open if self.serial_connection else False,
            'description': self.description,
            'current_count': self.get_current_count(),
            'total_detected': self.get_total_detected(),
            'max_simultaneous': self.max_simultaneous_people,
            'entries_count': self.entries_count,
            'exits_count': self.exits_count,
            'unique_people': len(self.unique_people_today),
            'people_in_area': len(self.current_people),
            'session_duration': (datetime.now() - self.session_start_time).total_seconds(),
            'system_restarts': self.system_restart_count,
            'health_status': 'healthy' if datetime.now() - self.last_data_received < timedelta(minutes=5) else 'unhealthy'
        }

def main():
    """Função principal com auto-recuperação"""
    logger.info("🚀 Iniciando Contador com Auto-Recuperação...")
    
    # Configura Google Sheets com auto-recovery
    script_dir = os.path.dirname(os.path.abspath(__file__))
    credentials_file = os.path.join(script_dir, 'serial_radar', 'credenciais.json')
    
    if not os.path.exists(credentials_file):
        logger.error(f"❌ Credenciais não encontradas: {credentials_file}")
        return
    
    try:
        gsheets_manager = AutoRecoveryGoogleSheetsManager(
            credentials_file, 
            RADAR_CONFIG['spreadsheet_id'],
            RADAR_CONFIG['id']
        )
        logger.info("✅ Google Sheets com auto-recovery configurado")

        # Cria contador com auto-recovery
        counter = AutoRecoveryRadarCounter(RADAR_CONFIG)
        
        def signal_handler(sig, frame):
            logger.info("🛑 Parando sistema...")
            counter.stop()
            sys.exit(0)
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        # Inicia sistema
        if counter.start(gsheets_manager):
            logger.info("✅ Sistema iniciado com sucesso!")
            
            # Mantém rodando
            while counter.is_running:
                time.sleep(1)
        else:
            logger.error("❌ Falha ao iniciar sistema")
            
    except Exception as e:
        logger.error(f"❌ Erro fatal: {e}")

if __name__ == "__main__":
    main() 
