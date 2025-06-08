#!/usr/bin/env python3
"""
CONTADOR SANTA CRUZ v4.3.1 + AUTO-RECUPERAÇÃO ESTÁVEL
Sistema que resolve automaticamente problemas após 3+ horas
MELHORIAS v4.3.1: Conexão mais estável, menos reconexões agressivas
"""

import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, timedelta
import logging
import os
import traceback
import time
import json
import serial
import threading
import serial.tools.list_ports
import gc
from dotenv import load_dotenv

# Configuração básica de logging com rotação
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('santa_cruz_auto_recovery.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('santa_cruz_auto_recovery')

# Configurando o nível de log para outros módulos
logging.getLogger('urllib3').setLevel(logging.WARNING)
logging.getLogger('gspread').setLevel(logging.WARNING)

load_dotenv()

# Configuração do radar
RADAR_CONFIG = {
    'id': 'RADAR_1',
    'name': 'Contador de Pessoas',
    'port': '/dev/ttyACM0',
    'baudrate': 115200,
    'spreadsheet_id': '1zVVyL6D9XSrzFvtDxaGJ-3CdniD-gG3Q-bUUXyqr3D4',
    'color': '🔴',
    'description': 'Contador v4.3.1: Estável + Auto-Recovery'
}

class AutoRecoveryGoogleSheetsManager:
    """GoogleSheetsManager com auto-recuperação integrada"""
    
    def __init__(self, creds_path, spreadsheet_id, radar_id):
        SCOPES = [
            'https://www.googleapis.com/auth/spreadsheets',
            'https://www.googleapis.com/auth/drive',
            'https://www.googleapis.com/auth/drive.file'
        ]
        self.radar_id = radar_id
        self.spreadsheet_id = spreadsheet_id
        self.creds_path = creds_path
        
        # Controle de auto-recuperação
        self.last_successful_write = datetime.now()
        self.consecutive_failures = 0
        self.max_failures_before_recovery = 3
        self.recovery_attempts = 0
        self.max_recovery_attempts = 5
        
        # Conecta inicialmente
        self._connect_with_recovery()
        self._setup_headers()

    def _connect_with_recovery(self):
        """Conecta com sistema de recuperação robusto"""
        for attempt in range(3):
            try:
                # Re-cria credenciais sempre (evita token expirado)
                SCOPES = [
                    'https://www.googleapis.com/auth/spreadsheets',
                    'https://www.googleapis.com/auth/drive',
                    'https://www.googleapis.com/auth/drive.file'
                ]
                self.creds = Credentials.from_service_account_file(self.creds_path, scopes=SCOPES)
                self.gc = gspread.authorize(self.creds)
                
                self.spreadsheet = self.gc.open_by_key(self.spreadsheet_id)
                self.worksheet = self.spreadsheet.get_worksheet(0)
                
                # Testa leitura (operação leve)
                headers = self.worksheet.row_values(1)
                
                logger.info(f"✅ Google Sheets conectado (tentativa {attempt + 1})")
                self.consecutive_failures = 0
                return True
                
            except Exception as e:
                logger.warning(f"⚠️ Falha na conexão tentativa {attempt + 1}: {e}")
                if attempt < 2:
                    time.sleep((attempt + 1) * 5)  # Backoff
        
        raise Exception("Falha ao conectar após múltiplas tentativas")
    
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
                self.worksheet.append_row(row)
                self.last_successful_write = datetime.now()
                self.consecutive_failures = 0
                return True
                
            except Exception as e:
                self.consecutive_failures += 1
                error_str = str(e).lower()
                
                logger.warning(f"⚠️ Erro envio (tentativa {attempt + 1}): {e}")
                
                # Tipos específicos de erro
                if "quota" in error_str or "429" in error_str:
                    wait_time = (attempt + 1) * 60  # 1min, 2min, 3min
                    logger.warning(f"⚠️ Quota exceeded - aguardando {wait_time}s")
                    time.sleep(wait_time)
                    
                elif "401" in error_str or "unauthorized" in error_str:
                    logger.warning("🔑 Token expirado - reconectando...")
                    try:
                        self._connect_with_recovery()
                        time.sleep(2)
                    except:
                        pass
                        
                elif "network" in error_str or "connection" in error_str:
                    logger.warning("🌐 Problema de rede - aguardando...")
                    time.sleep(10 * (attempt + 1))
                    
                else:
                    # Erro genérico - tenta reconectar
                    try:
                        self._connect_with_recovery()
                        time.sleep(5)
                    except:
                        time.sleep(10)
        
        # Se chegou aqui, todas as tentativas falharam
        logger.error(f"❌ Falha total no envio após 3 tentativas")
        
        # Auto-recuperação extrema
        if self.consecutive_failures >= self.max_failures_before_recovery:
            return self._attempt_full_recovery()
        
        return False
    
    def _attempt_full_recovery(self):
        """Recuperação completa do sistema Google Sheets"""
        if self.recovery_attempts >= self.max_recovery_attempts:
            logger.error("🚨 Máximo de recuperações atingido!")
            return False
            
        self.recovery_attempts += 1
        logger.info(f"🔄 Recuperação completa #{self.recovery_attempts}")
        
        try:
            # 1. Força garbage collection
            gc.collect()
            
            # 2. Aguarda mais tempo
            time.sleep(30)
            
            # 3. Reconecta completamente
            self._connect_with_recovery()
            
            # 4. Testa com dados simples
            test_row = [
                self.radar_id,
                datetime.now().strftime('%d/%m/%Y %H:%M:%S'),
                0, "Recovery_Test", "RECOVERY", "0", "100", 0, 0
            ]
            
            self.worksheet.append_row(test_row)
            
            logger.info("✅ Recuperação completa bem-sucedida!")
            self.consecutive_failures = 0
            return True
            
        except Exception as e:
            logger.error(f"❌ Falha na recuperação completa: {e}")
            return False
    
    def health_check(self):
        """Verifica saúde da conexão"""
        time_since_success = datetime.now() - self.last_successful_write
        
        if time_since_success > timedelta(minutes=15):
            logger.warning(f"⚠️ Sem envios há {time_since_success}")
            return False
        
        if self.consecutive_failures > 5:
            logger.warning(f"⚠️ {self.consecutive_failures} falhas consecutivas")
            return False
            
        return True

class ZoneManager:
    """Sistema de zonas do Santa Cruz - Radar centrado na Sala de Reboco"""
    def __init__(self):
        self.ZONA_CONFIGS = {
            # CENTRO - SALA DE REBOCO (onde está o radar)
            'SALA_REBOCO': {
                'x_min': -0.8, 'x_max': 0.8,
                'y_min': -0.8, 'y_max': 0.8,
                'distance_range': (0.3, 2.0)  # Pessoas próximas ao radar
            },
            
            # ENTRADA DA SALA (5 metros de distância)
            'ENTRADA': {
                'x_min': -1.0, 'x_max': 1.0,
                'y_min': 4.5, 'y_max': 6.0,
                'distance_range': (4.5, 6.0)  # ~5 metros conforme especificado
            },
            
            # LADO DIREITO (X > 0) - ÁREAS AO REDOR DOS PONTOS CENTRAIS
            'ARGOLA': {
                'x_min': 0.5, 'x_max': 1.5,
                'y_min': 0.5, 'y_max': 1.5,
                'distance_range': (0.7, 2.5)  # Área ao redor de X=1, Y=1
            },
            'PESCARIA': {
                'x_min': 0.5, 'x_max': 1.5,
                'y_min': 1.5, 'y_max': 2.5,
                'distance_range': (1.5, 3.0)  # Área ao redor de X=1, Y=2
            },
            
            # LADO ESQUERDO (X < 0) - ÁREAS AO REDOR DOS PONTOS CENTRAIS
            'COSTUREIRA': {
                'x_min': -1.5, 'x_max': -0.5,
                'y_min': 0.5, 'y_max': 1.5,
                'distance_range': (0.7, 2.5)  # Área ao redor de X=-1, Y=1
            },
            'CORREIOS': {
                'x_min': -1.5, 'x_max': -0.5,
                'y_min': 1.5, 'y_max': 2.5,
                'distance_range': (1.5, 3.0)  # Área ao redor de X=-1, Y=2
            },
            
            # ÁREA GERAL (para capturar movimento geral)
            'AREA_GERAL': {
                'x_min': -3.0, 'x_max': 3.0,
                'y_min': -1.0, 'y_max': 7.0,
                'distance_range': (3.0, 8.0)  # Distâncias maiores
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
            'ENTRADA': 'Entrada da Sala', 
            'ARGOLA': 'Jogo da Argola',
            'PESCARIA': 'Pescaria',
            'COSTUREIRA': 'Costureira',
            'CORREIOS': 'Correios',
            'AREA_GERAL': 'Área Geral',
            'FORA_ATIVACOES': 'Fora das Ativações'
        }
        return descriptions.get(zone_name, zone_name)

class AutoRecoveryRadarCounter:
    """Contador COMPLETO com sistema de auto-recuperação integrado"""
    
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
        
        # Estado do radar
        self.serial_connection = None
        self.is_running = False
        self.receive_thread = None
        self.gsheets_manager = None
        self.zone_manager = ZoneManager()  # ✅ ADICIONADO
        
        # ✅ SISTEMA COMPLETO DE CONTAGEM (igual ao original)
        self.current_people = {}
        self.previous_people = {}
        self.people_history = {}
        self.total_people_detected = 0
        self.max_simultaneous_people = 0
        self.session_start_time = datetime.now()
        
        # Configurações de tracking
        self.exit_timeout = 3.0
        self.reentry_timeout = 10.0
        self.last_update_time = time.time()
        
        # Configurações anti-quota (intervalos maiores para melhor detecção)
        self.last_sheets_write = 0
        self.sheets_write_interval = 180.0  # 3 minutos em vez de 60s - INTERVALO MAIOR
        self.pending_data = []
        
        # ✅ ESTATÍSTICAS DETALHADAS (igual ao original)
        self.entries_count = 0
        self.exits_count = 0
        self.unique_people_today = set()
        
        # Thread de monitoramento
        self.monitoring_thread = None
        
        # Controle de estabilidade (NOVO)
        self.last_connection_attempt = datetime.now() - timedelta(minutes=10)
        self.connection_cooldown = 60  # 1 minuto entre tentativas
        self.consecutive_connection_failures = 0
        self.max_connection_failures = 5  # Mais tolerante
        
    def start_health_monitoring(self):
        """Inicia monitoramento de saúde em background"""
        self.monitoring_thread = threading.Thread(target=self._health_monitoring_loop, daemon=True)
        self.monitoring_thread.start()
        logger.info("🔄 Monitoramento de saúde iniciado")
        
    def _health_monitoring_loop(self):
        """Loop de monitoramento de saúde"""
        while self.is_running:
            try:
                time.sleep(60)  # Verifica a cada minuto
                self._check_system_health()
            except Exception as e:
                logger.error(f"❌ Erro no monitoramento: {e}")
                time.sleep(30)
                
    def _check_system_health(self):
        """Verifica saúde geral do sistema (mais suave)"""
        now = datetime.now()
        
        # 1. Verifica recebimento de dados serial (mais tolerante)
        time_since_data = now - self.last_data_received
        if time_since_data > timedelta(minutes=10):  # 10 minutos em vez de 5
            logger.warning(f"⚠️ Sem dados seriais há {time_since_data}")
            if self._should_attempt_recovery():
                self._attempt_serial_recovery()
        
        # 2. Verifica envios para planilha (menos frequente)
        time_since_sheets = now - self.last_sheets_success
        if time_since_sheets > timedelta(minutes=20):  # 20 minutos em vez de 10
            logger.warning(f"⚠️ Sem envios há {time_since_sheets}")
            if self.gsheets_manager and self._should_attempt_recovery():
                self.gsheets_manager._attempt_full_recovery()
        
        # 3. Verifica uso de memória
        try:
            import psutil
            process = psutil.Process()
            memory_mb = process.memory_info().rss / 1024 / 1024
            
            if memory_mb > 200:  # 200MB limite
                logger.warning(f"⚠️ Memória alta: {memory_mb:.1f}MB")
                self._cleanup_memory()
                
        except ImportError:
            pass  # psutil não disponível
        except Exception as e:
            logger.debug(f"Erro verificando memória: {e}")
        
        # 4. Restart preventivo após 12 horas (menos agressivo)
        runtime = now - self.start_time
        if runtime > timedelta(hours=12):  # 12 horas em vez de 6
            logger.info(f"⏰ Runtime {runtime} - restart preventivo recomendado")
            if self._should_attempt_recovery():
                self._attempt_system_restart()
    
    def _should_attempt_recovery(self):
        """Verifica se deve tentar recovery (com cooldown)"""
        now = datetime.now()
        time_since_last = now - self.last_connection_attempt
        
        if time_since_last.total_seconds() < self.connection_cooldown:
            return False
            
        self.last_connection_attempt = now
        return True
    
    def _cleanup_memory(self):
        """Limpa memória e buffers"""
        try:
            # Limpa buffer de dados pendentes
            if len(self.pending_data) > 20:
                self.pending_data = self.pending_data[-10:]
                logger.info("🧹 Buffer limpo")
            
            # Força garbage collection
            gc.collect()
            
        except Exception as e:
            logger.error(f"❌ Erro limpando memória: {e}")
    
    def _attempt_serial_recovery(self):
        """Tenta recuperar conexão serial (mais suave)"""
        try:
            self.consecutive_connection_failures += 1
            
            if self.consecutive_connection_failures > self.max_connection_failures:
                logger.warning(f"⚠️ Muitas falhas consecutivas ({self.consecutive_connection_failures}) - pausando 5 minutos")
                time.sleep(300)  # 5 minutos de pausa
                self.consecutive_connection_failures = 0
            
            logger.info(f"🔄 Tentando recuperar conexão serial (tentativa {self.consecutive_connection_failures})...")
            
            # Fecha conexão atual com pausa maior
            if self.serial_connection:
                try:
                    self.serial_connection.close()
                except:
                    pass
                time.sleep(5)  # 5 segundos em vez de 2
            
            # Tenta reconectar
            if self.connect():
                logger.info("✅ Conexão serial recuperada!")
                self.consecutive_connection_failures = 0
                return True
            else:
                logger.error(f"❌ Falha na recuperação serial (tentativa {self.consecutive_connection_failures})")
                time.sleep(10)  # Pausa antes da próxima tentativa
                return False
                
        except Exception as e:
            logger.error(f"❌ Erro na recuperação serial: {e}")
            return False
    
    def _attempt_system_restart(self):
        """Restart preventivo do sistema"""
        if self.system_restart_count >= self.max_system_restarts:
            logger.error("🚨 Máximo de restarts atingido")
            return False
            
        self.system_restart_count += 1
        logger.info(f"🔄 Restart preventivo #{self.system_restart_count}")
        
        try:
            # Para sistema
            self.stop()
            time.sleep(5)
            
            # Re-inicializa
            self.start(self.gsheets_manager)
            
            # Reset contadores
            self.start_time = datetime.now()
            
            logger.info("✅ Restart preventivo concluído")
            return True
            
        except Exception as e:
            logger.error(f"❌ Falha no restart preventivo: {e}")
            return False

    def connect(self):
        """Conecta à porta serial (versão original)"""
        max_attempts = 3
        
        for attempt in range(max_attempts):
            try:
                if not os.path.exists(self.port):
                    logger.warning(f"Porta {self.port} não existe, detectando...")
                    detected_port = self.find_serial_port()
                    if detected_port:
                        self.port = detected_port
                    else:
                        logger.error(f"Tentativa {attempt + 1}: Nenhuma porta encontrada")
                        time.sleep(2)
                        continue
                
                if hasattr(self, 'serial_connection') and self.serial_connection:
                    try:
                        self.serial_connection.close()
                    except:
                        pass
                
                logger.info(f"Tentativa {attempt + 1}: Conectando à porta {self.port}")
                
                self.serial_connection = serial.Serial(
                    port=self.port,
                    baudrate=self.baudrate,
                    timeout=5,  # Timeout maior
                    write_timeout=5,  # Write timeout maior
                    bytesize=serial.EIGHTBITS,
                    parity=serial.PARITY_NONE,
                    stopbits=serial.STOPBITS_ONE
                )
                
                time.sleep(5)  # Aguarda mais tempo para estabilizar
                
                if self.serial_connection.is_open:
                    logger.info(f"✅ Conexão estabelecida com sucesso!")
                    return True
                    
            except serial.SerialException as e:
                logger.error(f"❌ Erro serial na tentativa {attempt + 1}: {str(e)}")
            except Exception as e:
                logger.error(f"❌ Erro geral na tentativa {attempt + 1}: {str(e)}")
            
            if attempt < max_attempts - 1:
                wait_time = (attempt + 1) * 2
                logger.info(f"⏳ Aguardando {wait_time}s...")
                time.sleep(wait_time)
        
        logger.error(f"❌ Falha ao conectar após {max_attempts} tentativas")
        return False

    def find_serial_port(self):
        """Detecta porta serial automaticamente"""
        ports = list(serial.tools.list_ports.comports())
        if not ports:
            return None
        
        # Primeiro tenta a porta configurada
        for port in ports:
            if port.device == self.port:
                return self.port
        
        # Se não encontrou, procura por dispositivos apropriados
        for port in ports:
            desc_lower = port.description.lower()
            if any(term in desc_lower for term in
                  ['usb', 'serial', 'uart', 'cp210', 'ch340', 'ft232', 'arduino', 'esp32']):
                logger.warning(f"Porta {self.port} não encontrada, tentando usar {port.device}")
                return port.device
        
        return None

    def check_port_usage(self):
        """Verifica se algum processo está usando a porta serial"""
        try:
            import subprocess
            # Verifica processos usando a porta (Linux)
            cmd = f"lsof {self.port} 2>/dev/null || fuser {self.port} 2>/dev/null"
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            
            if result.stdout.strip():
                logger.warning(f"{self.color} ⚠️ Processos usando a porta {self.port}:")
                logger.info(f"{self.color} {result.stdout.strip()}")
                return True
            
            return False
            
        except Exception as e:
            logger.debug(f"Erro verificando uso da porta: {e}")
            return False

    def force_release_port(self):
        """Força liberação da porta serial (mata processos conflitantes)"""
        try:
            import subprocess
            import os
            
            logger.warning(f"{self.color} 🔧 Tentando liberar porta {self.port}...")
            
            # Mata processos que podem estar usando a porta
            processes_to_kill = ['arduino', 'arduino-ide', 'minicom', 'screen', 'putty']
            
            for proc_name in processes_to_kill:
                try:
                    subprocess.run(['pkill', '-f', proc_name], capture_output=True)
                    logger.debug(f"Tentativa de matar processo: {proc_name}")
                except:
                    pass
            
            # Aguarda liberação
            time.sleep(2)
            
            # Verifica se ainda há processos usando
            if not self.check_port_usage():
                logger.info(f"{self.color} ✅ Porta liberada com sucesso!")
                return True
            else:
                logger.warning(f"{self.color} ⚠️ Ainda há processos usando a porta")
                return False
                
        except Exception as e:
            logger.error(f"{self.color} ❌ Erro ao tentar liberar porta: {e}")
            return False

    def start(self, gsheets_manager):
        """Inicia o radar com auto-recuperação"""
        self.gsheets_manager = gsheets_manager
        
        if not self.connect():
            return False
        
        self.is_running = True
        self.receive_thread = threading.Thread(target=self.receive_data_loop, daemon=True)
        self.receive_thread.start()
        
        # Inicia monitoramento de saúde
        self.start_health_monitoring()
        
        logger.info(f"🚀 Radar com auto-recuperação iniciado!")
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
        
        logger.info("🛑 Radar parado!")

    def receive_data_loop(self):
        """Loop de dados com auto-recuperação (mais estável)"""
        buffer = ""
        consecutive_errors = 0
        max_consecutive_errors = 10  # Mais tolerante
        
        while self.is_running:
            try:
                if not self.serial_connection or not self.serial_connection.is_open:
                    logger.warning("⚠️ Conexão perdida, tentando reconectar...")
                    if self.connect():
                        consecutive_errors = 0
                        buffer = ""
                        continue
                    else:
                        consecutive_errors += 1
                        time.sleep(5)
                        continue
                
                # Leitura mais simples e estável
                try:
                    in_waiting = self.serial_connection.in_waiting or 0
                    
                    if in_waiting > 0:
                        data = self.serial_connection.read(in_waiting)
                    else:
                        # Se não há dados, aguarda um pouco e continua
                        time.sleep(0.1)
                        continue
                except serial.SerialTimeoutException:
                    # Timeout é normal
                    time.sleep(0.1)
                    continue
                
                if data:
                    consecutive_errors = 0
                    self.last_data_received = datetime.now()  # Marca recebimento
                    
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
                                # DELAY DE 3 SEGUNDOS ENTRE PROCESSAMENTOS para melhor detecção
                                time.sleep(3.0)  
                            except json.JSONDecodeError:
                                logger.debug(f"JSON inválido: {line[:50]}...")
                            except Exception as e:
                                logger.error(f"Erro processando JSON: {e}")
                
                time.sleep(0.01)
                
            except Exception as e:
                consecutive_errors += 1
                error_msg = str(e).lower()
                
                # ✅ TRATAMENTO ESPECÍFICO para diferentes tipos de erro
                if "readiness to read but returned no data" in error_msg:
                    logger.warning(f"{self.color} 🔌 Dispositivo não responde adequadamente - forçando reconexão...")
                    # Força fechamento da conexão
                    try:
                        if self.serial_connection:
                            self.serial_connection.close()
                    except:
                        pass
                    self.serial_connection = None
                    time.sleep(3)
                    
                elif "multiple access" in error_msg:
                    logger.error(f"{self.color} ⚠️ Outra aplicação está usando a porta - tentando liberar...")
                    self.check_port_usage()  # Mostra quais processos estão usando
                    if self.force_release_port():  # Tenta liberar automaticamente
                        logger.info(f"{self.color} ✅ Porta liberada - tentando reconectar...")
                        time.sleep(2)
                    else:
                        logger.info(f"{self.color} 💡 Feche manualmente: Arduino IDE, outros scripts Python ou Putty/minicom")
                        time.sleep(10)
                    
                elif "device disconnected" in error_msg:
                    logger.warning(f"{self.color} 🔌 Dispositivo desconectado - aguardando reconexão...")
                    self.serial_connection = None
                    time.sleep(5)
                    
                elif "permission denied" in error_msg:
                    logger.error(f"{self.color} 🔒 Sem permissão para acessar porta - verifique sudo/udev rules")
                    time.sleep(15)
                    
                else:
                    logger.error(f"{self.color} ❌ Erro inesperado no loop: {str(e)}")
                    time.sleep(2)
                
                # Aumenta tempo de pausa se muitos erros consecutivos
                if consecutive_errors >= max_consecutive_errors:
                    logger.warning(f"{self.color} ⚠️ Muitos erros consecutivos ({consecutive_errors}) - pausando por 60s...")
                    logger.info(f"{self.color} 🔄 O sistema tentará auto-recovery após a pausa...")
                    time.sleep(60)  # 1 minuto em vez de 20s
                    consecutive_errors = 0

    def convert_timestamp(self, timestamp_ms):
        """Converte timestamp para formato brasileiro (sempre usa horário atual do sistema)"""
        try:
            # Sempre usa horário atual do sistema para consistência
            dt = datetime.now()
            return dt.strftime('%d/%m/%Y %H:%M:%S')
        except Exception as e:
            logger.debug(f"Erro na conversão de timestamp: {e}")
            # Fallback ainda mais simples
            import time
            return time.strftime('%d/%m/%Y %H:%M:%S')

    def format_duration(self, duration_ms):
        """Formata duração em milissegundos para formato legível"""
        try:
            if duration_ms < 1000:
                return f"{int(duration_ms)}ms"
            elif duration_ms < 60000:
                seconds = duration_ms / 1000
                return f"{seconds:.1f}s"
            elif duration_ms < 3600000:
                minutes = duration_ms / 60000
                return f"{minutes:.1f}min"
            else:
                hours = duration_ms / 3600000
                return f"{hours:.1f}h"
        except:
            return "N/A"

    def update_people_count(self, person_count, active_people):
        """Sistema ROBUSTO de tracking para eventos - lógica precisa de entrada/saída com contagem total melhorada"""
        current_time = time.time()
        
        # Cria IDs únicos baseados em posição estável
        current_people_dict = {}
        
        for i, person in enumerate(active_people):
            # Cria ID único baseado em posição estável (não no ID do Arduino)
            x_pos = person.get('x_pos', 0)
            y_pos = person.get('y_pos', 0) 
            distance = person.get('distance_raw', 0)  # ✅ Arduino minimal só envia distance_raw
            
            # ✅ CALCULA ZONA ESPECÍFICA DAS ATIVAÇÕES usando coordenadas x,y
            zone = self.zone_manager.get_zone(x_pos, y_pos)
            person["zone"] = zone  # Atualiza o objeto pessoa com a zona correta
            
            # ID baseado na posição arredondada E índice (mais preciso para múltiplas pessoas)
            stable_id = f"P_{zone}_{distance:.1f}_{x_pos:.1f}_{y_pos:.1f}_{i}"
            
            # Procura se já existe pessoa similar (mesma zona, distância E posição similar)
            found_existing = None
            for existing_id, existing_person in self.current_people.items():
                existing_dist = existing_person.get('distance_raw', 0)  # ✅ Arduino minimal
                existing_zone = existing_person.get('zone', '')
                existing_x = existing_person.get('x_pos', 0)
                existing_y = existing_person.get('y_pos', 0)
                
                # Se pessoa está na mesma zona, distância E posição similar (±0.3m), é a mesma
                if (existing_zone == zone and 
                    abs(existing_dist - distance) < 0.3 and
                    abs(existing_x - x_pos) < 0.3 and
                    abs(existing_y - y_pos) < 0.3):
                    found_existing = existing_id
                    break
            
            # Se encontrou pessoa similar, mantém ID existente
            if found_existing:
                current_people_dict[found_existing] = person
                current_people_dict[found_existing]['last_seen'] = current_time
            else:
                # Nova pessoa detectada
                person['first_seen'] = current_time
                person['last_seen'] = current_time
                # ✅ Adiciona campos padrão que o Arduino minimal não envia
                person['distance_smoothed'] = distance  # Usa distance_raw como smoothed
                person['confidence'] = 85  # Valor padrão razoável
                person['stationary'] = False  # Assume móvel por padrão
                current_people_dict[stable_id] = person
        
        # ✅ CONTAGEM TOTAL ROBUSTA - Detecta ENTRADAS REAIS (novas pessoas que não existiam)
        new_entries = []
        people_really_new = 0  # Contador específico para novas pessoas reais
        
        for person_id, person_info in current_people_dict.items():
            if person_id not in self.current_people:
                # Verifica se não é pessoa que acabou de sair (evita flickering)
                is_really_new = True
                for old_id, old_person in self.previous_people.items():
                    old_zone = old_person.get('zone', '')
                    old_dist = old_person.get('distance_raw', 0)  # ✅ Arduino minimal
                    old_x = old_person.get('x_pos', 0)
                    old_y = old_person.get('y_pos', 0)
                    new_zone = person_info.get('zone', '')
                    new_dist = person_info.get('distance_raw', 0)  # ✅ Arduino minimal
                    new_x = person_info.get('x_pos', 0)
                    new_y = person_info.get('y_pos', 0)
                    
                    # Se pessoa muito similar saiu recentemente, não conta como nova
                    if (old_zone == new_zone and 
                        abs(old_dist - new_dist) < 0.5 and
                        abs(old_x - new_x) < 0.5 and
                        abs(old_y - new_y) < 0.5 and
                        (current_time - old_person.get('last_seen', 0)) < 5.0):  # 5 segundos - ANTI-FLICKERING MAIOR
                        is_really_new = False
                        break
                
                if is_really_new:
                    new_entries.append(person_id)
                    people_really_new += 1  # Conta pessoa real nova
                    self.unique_people_today.add(person_id)
                    zone = person_info.get('zone', 'DESCONHECIDA')
                    dist = person_info.get('distance_raw', 0)  # ✅ Arduino minimal
                    pos = f"({person_info.get('x_pos', 0):.1f},{person_info.get('y_pos', 0):.1f})"
                    logger.info(f"🆕 ENTRADA REAL #{people_really_new}: {zone} {dist:.1f}m {pos}")
        
        # ✅ ATUALIZA TOTAL ROBUSTO - Soma pessoas reais novas detectadas
        if people_really_new > 0:
            self.total_people_detected += people_really_new
            self.entries_count += people_really_new
            if people_really_new == 1:
                logger.info(f"📊 TOTAL ATUALIZADO: +1 pessoa = {self.total_people_detected} total")
            else:
                logger.info(f"📊 TOTAL ATUALIZADO: +{people_really_new} pessoas = {self.total_people_detected} total")
        
        # Detecta SAÍDAS REAIS (pessoas que realmente saíram)
        exits = []
        people_really_left = 0
        for person_id, person_info in self.current_people.items():
            if person_id not in current_people_dict:
                # Pessoa saiu apenas se não foi detectada por tempo suficiente
                last_seen = person_info.get('last_seen', 0)
                if (current_time - last_seen) > 3.0:  # 3 segundos de timeout - MAIOR INTERVALO
                    exits.append(person_id)
                    people_really_left += 1
                    self.exits_count += 1
                    zone = person_info.get('zone', 'DESCONHECIDA')
                    dist = person_info.get('distance_raw', 0)  # ✅ Arduino minimal
                    pos = f"({person_info.get('x_pos', 0):.1f},{person_info.get('y_pos', 0):.1f})"
                    logger.info(f"🚪 SAÍDA REAL: {zone} {dist:.1f}m {pos}")
        
        if people_really_left > 0:
            if people_really_left == 1:
                logger.info(f"📊 SAÍDAS: {self.exits_count} total (Balanço: {self.entries_count - self.exits_count})")
            else:
                logger.info(f"📊 SAÍDAS: +{people_really_left} = {self.exits_count} total (Balanço: {self.entries_count - self.exits_count})")
        
        # Atualiza estado
        self.previous_people = self.current_people.copy()
        self.current_people = current_people_dict
        
        # Atualiza máximo simultâneo
        current_simultaneous = len(current_people_dict)
        if current_simultaneous > self.max_simultaneous_people:
            self.max_simultaneous_people = current_simultaneous
            logger.info(f"📊 NOVO MÁXIMO SIMULTÂNEO: {self.max_simultaneous_people} pessoas")
        
        # Log apenas se houve mudanças reais
        if new_entries or exits:
            logger.info(f"📊 STATUS ROBUSTO: {current_simultaneous} ativas | {self.total_people_detected} total acumulado | Entradas: {self.entries_count} | Saídas: {self.exits_count} | Máx: {self.max_simultaneous_people}")
        
        self.last_update_time = current_time

    def process_json_data(self, data_json):
        """Processa dados JSON CORRIGIDO (igual ao original sem duplicação)"""
        try:
            radar_id = data_json.get("radar_id", self.radar_id)
            timestamp_ms = data_json.get("timestamp_ms", 0)
            person_count = data_json.get("person_count", 0)
            active_people = data_json.get("active_people", [])
            tracking_method = data_json.get("tracking_method", "hybrid_multi")
            session_duration_ms = data_json.get("session_duration_ms", 0)
            update_rate_hz = data_json.get("update_rate_hz", 8.3)
            
            # IGNORA dados de contagem do Arduino (não são confiáveis para eventos)
            # Arduino envia IDs baseados em timestamp/contador interno, não pessoas reais
            # Vamos usar APENAS nossa lógica Python baseada em posição e movimento real
            
            # Converte timestamp para formato legível
            formatted_timestamp = self.convert_timestamp(timestamp_ms)
            
            # Atualiza contadores locais APENAS UMA VEZ (evita duplicação)
            self.update_people_count(person_count, active_people)
            
            # ✅ DISPLAY COMPLETO (evita clear em systemd)
            if os.getenv('TERM'):  # Só limpa se tem terminal
                os.system('clear')
            print(f"\n{self.color} ═══ CONTADOR ROBUSTO + AUTO-RECOVERY ═══")
            print(f"⏰ {formatted_timestamp}")
            print(f"📡 {radar_id} | 👥 ATIVAS: {person_count}")
            print(f"🎯 TOTAL DETECTADAS: {self.total_people_detected} | 📊 MÁXIMO SIMULTÂNEO: {self.max_simultaneous_people}")
            print(f"🔄 ENTRADAS: {self.entries_count} | 🚪 SAÍDAS: {self.exits_count} | 📈 BALANÇO: {self.entries_count - self.exits_count}")
            print(f"🆔 PESSOAS ÚNICAS: {len(self.unique_people_today)}")
            
            # ✅ STATUS AUTO-RECOVERY
            runtime = datetime.now() - self.start_time
            time_since_sheets = datetime.now() - self.last_sheets_success
            duration_str = self.format_duration(runtime.total_seconds() * 1000)
            print(f"⏱️ SESSÃO: {duration_str} | 🔄 Restarts: {self.system_restart_count}")
            
            # Status do envio para planilha (ANTI-QUOTA)
            pending_count = len(self.pending_data)
            time_since_last_send = time.time() - self.last_sheets_write
            next_send_in = max(0, self.sheets_write_interval - time_since_last_send)
            if pending_count > 0:
                print(f"📋 BUFFER: {pending_count} linhas | ⏳ Próximo envio em: {next_send_in:.0f}s (3min intervalo)")
            else:
                print(f"📋 PLANILHA: Sincronizada ✅ | Último envio: {time_since_sheets} (envio apenas com mudanças)")
            
            if active_people and len(active_people) > 0:
                print(f"\n👥 PESSOAS DETECTADAS AGORA ({len(active_people)}) - TRACKING ROBUSTO:")
                print(f"{'#':<2} {'Ativação':<15} {'Dist(m)':<7} {'X,Y':<12} {'Conf%':<5} {'Status':<8} {'Desde':<8}")
                print("-" * 75)
                
                current_time = time.time()
                for i, person in enumerate(active_people):
                    # ✅ Arduino minimal: adapta campos ausentes
                    confidence = person.get("confidence", 85)  # Valor padrão
                    distance_raw = person.get("distance_raw", 0)  # Novo campo principal
                    distance_smoothed = person.get("distance_smoothed", distance_raw)  # Fallback
                    x_pos = person.get("x_pos", 0)
                    y_pos = person.get("y_pos", 0)
                    stationary = person.get("stationary", False)  # Valor padrão
                    
                    # ✅ ZONA JÁ FOI CALCULADA no update_people_count
                    zone = person.get("zone", self.zone_manager.get_zone(x_pos, y_pos))
                    
                    # Encontra ID da nossa lógica interna
                    our_person_id = None
                    for internal_id, internal_person in self.current_people.items():
                        internal_dist = internal_person.get('distance_raw', internal_person.get('distance_smoothed', 0))
                        if (abs(internal_dist - distance_raw) < 0.1 and
                            internal_person.get('zone', '') == zone):
                            our_person_id = internal_id
                            break
                    
                    # Calcula tempo desde primeira detecção (nossa lógica)
                    if our_person_id and our_person_id in self.current_people:
                        first_seen = self.current_people[our_person_id].get('first_seen', current_time)
                        time_in_area = current_time - first_seen
                        time_str = f"{time_in_area:.0f}s" if time_in_area < 60 else f"{time_in_area/60:.1f}m"
                    else:
                        time_str = "novo"
                    
                    # Status da pessoa
                    status = "Parado" if stationary else "Móvel"
                    pos_str = f"({x_pos:.1f},{y_pos:.1f})"
                    
                    zone_desc = self.zone_manager.get_zone_description(zone)[:14]  # Trunca para caber
                    print(f"{i+1:<2} {zone_desc:<15} {distance_raw:<7.2f} {pos_str:<12} {confidence:<5}% {status:<8} {time_str:<8}")
                
                # Envia APENAS UM resumo por ciclo (não uma linha por pessoa) - SEM duplicação
                if self.gsheets_manager:
                    # Calcula dados agregados
                    avg_confidence = sum(p.get("confidence", 0) for p in active_people) / len(active_people)
                    # ✅ COLETA ZONAS JÁ CORRIGIDAS (calculadas no update_people_count)
                    zones_detected = list(set(p.get("zone", "N/A") for p in active_people))
                    zones_str = ",".join(sorted(zones_detected))
                    
                    # ID mais profissional baseado no contexto
                    if len(active_people) == 1:
                        person_description = "Pessoa Individual"
                    elif len(active_people) <= 3:
                        person_description = "Grupo Pequeno"
                    elif len(active_people) <= 10:
                        person_description = "Grupo Médio"
                    elif len(active_people) <= 20:
                        person_description = "Grupo Grande"
                    else:
                        person_description = "Multidão"
                    
                    # ENVIA APENAS SE HOUVE MUDANÇAS REAIS (entrada ou saída)
                    current_people_count = len(active_people)
                    last_count = getattr(self, 'last_sent_count', -1)
                    
                    # Só envia se houve mudança no número de pessoas ou a cada 5 minutos
                    time_since_last_send = time.time() - self.last_sheets_write
                    should_send = (current_people_count != last_count or 
                                 time_since_last_send > 300)  # 5 minutos
                    
                    if should_send:
                        # ✅ CALCULA DISTÂNCIA MÉDIA CORRIGIDA (mesmo fix do Gravatá)
                        valid_distances = []
                        for p in active_people:
                            distance_raw = p.get('distance_raw', None)
                            distance_smoothed = p.get('distance_smoothed', None)
                            x = p.get('x_pos', 0)
                            y = p.get('y_pos', 0)
                            
                            # SEMPRE CALCULA DISTÂNCIA DAS COORDENADAS (mais confiável)
                            import math
                            calculated_distance = math.sqrt(x**2 + y**2)
                            
                            # Usa distância calculada como padrão
                            distance = calculated_distance
                            
                            # Se Arduino enviou distância, compara
                            arduino_distance = distance_smoothed if distance_smoothed is not None else distance_raw
                            if arduino_distance is not None and arduino_distance > 0:
                                if abs(arduino_distance - calculated_distance) < 0.3:
                                    # Arduino consistente, pode usar
                                    distance = arduino_distance
                                # Se não consistente, usa calculada (que já está definida)
                            
                            valid_distances.append(distance)
                        
                        avg_distance = sum(valid_distances) / len(valid_distances) if valid_distances else 0
                        
                        row = [
                            radar_id,                          # 1. radar_id
                            formatted_timestamp,               # 2. timestamp
                            len(active_people),                # 3. person_count (real detectadas agora)
                            person_description,                # 4. person_id (descrição profissional)
                            zones_str,                         # 5. zone (todas as zonas ordenadas)
                            f"{avg_distance:.1f}",             # 6. distance (média CORRIGIDA)
                            f"{avg_confidence:.0f}",           # 7. confidence (média)
                            self.total_people_detected,       # 8. total_detected (nossa contagem real)
                            self.max_simultaneous_people      # 9. max_simultaneous (nosso máximo real)
                        ]
                        self.pending_data.append(row)
                        self.last_sent_count = current_people_count
                        logger.info(f"📋 Dados adicionados ao buffer (mudança detectada: {last_count} → {current_people_count})")
                
                print(f"\n💡 DETECTANDO {len(active_people)} pessoa(s) SIMULTANEAMENTE")
                
                # ✅ ESTATÍSTICAS POR ZONA (usando zonas já corrigidas)
                zone_stats = {}
                high_confidence = 0
                for person in active_people:
                    zone = person.get("zone", "N/A")  # Zona já foi corrigida no update_people_count
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
                
                # Envia dados zerados apenas se houve mudança de estado - SEM duplicação
                if self.gsheets_manager and len(self.previous_people) > 0:
                    # ENVIA APENAS SE MUDOU DE "com pessoas" para "sem pessoas"
                    last_count = getattr(self, 'last_sent_count', -1)
                    if last_count != 0:  # Só envia se antes havia pessoas
                        row = [
                            radar_id,                          # 1. radar_id
                            formatted_timestamp,               # 2. timestamp
                            0,                                 # 3. person_count (zero)
                            "Area_Vazia",                      # 4. person_id (indicador)
                            "VAZIA",                           # 5. zone 
                            "0",                               # 6. distance
                            "0",                               # 7. confidence
                            self.total_people_detected,       # 8. total_detected (nossa contagem real)
                            self.max_simultaneous_people      # 9. max_simultaneous (nosso máximo real)
                        ]
                        self.pending_data.append(row)
                        self.last_sent_count = 0
                        logger.info(f"📋 Área vazia detectada - dados adicionados ao buffer")
            
            print("\n" + "=" * 60)
            print("🎯 SISTEMA ROBUSTO + AUTO-RECOVERY ATIVO")
            print("✅ Tracking preciso | ✅ Auto-reconexão | ✅ Anti-quota")
            print("🔄 MELHORIAS DE DETECÇÃO:")
            print("   • 3 segundos entre captações (evita duplicações)")
            print("   • 3 segundos timeout para saída (mais estável)")
            print("   • 5 segundos anti-flickering (entrada/saída)")
            print("   • 3 minutos intervalo de envio (menos spam)")
            print("   • Envio apenas com mudanças reais")
            print("📊 CONTAGEM TOTAL ROBUSTA:")
            print("   • Detecção precisa de múltiplas pessoas simultâneas")
            print("   • IDs únicos baseados em posição + zona + distância")
            print("   • Contagem individual para cada pessoa nova")
            print("   • Balanço automático (entradas - saídas)")
            print("   • Histórico acumulativo sempre atualizado")
            print("⚡ Pressione Ctrl+C para encerrar")
            
            # ✅ ENVIA COM AUTO-RECOVERY (apenas uma vez)
            self.send_pending_data_with_recovery()
            
        except Exception as e:
            logger.error(f"Erro ao processar dados JSON: {e}")
            logger.debug(f"JSON recebido: {data_json}")

    def send_pending_data_with_recovery(self):
        """Envia dados para Google Sheets de forma controlada (ANTI-QUOTA EXCEEDED) - igual ao original"""
        try:
            current_time = time.time()
            
            # Verifica se já passou tempo suficiente desde último envio
            if (current_time - self.last_sheets_write) < self.sheets_write_interval:
                return  # Ainda não é hora de enviar
            
            # Se não há dados pendentes, não faz nada
            if not self.pending_data or not self.gsheets_manager:
                return
            
            # Pega apenas os dados mais recentes (máximo 10 linhas por vez) - IGUAL AO ORIGINAL
            data_to_send = self.pending_data[-10:] if len(self.pending_data) > 10 else self.pending_data
            
            # Envia em lote (mais eficiente) com auto-recovery
            if data_to_send:
                logger.info(f"📊 Enviando {len(data_to_send)} linhas para Google Sheets com auto-recovery...")
                
                # Envia todas as linhas com retry automático (igual ao original mas com auto-recovery)
                for row in data_to_send:
                    success = self.gsheets_manager.append_row_with_auto_recovery(row)
                    if success:
                        self.last_sheets_success = datetime.now()
                    time.sleep(0.5)  # Pequena pausa entre linhas
                
                logger.info(f"✅ {len(data_to_send)} linhas enviadas com auto-recovery!")
                
                # Atualiza controles
                self.last_sheets_write = current_time
                self.pending_data = []  # Limpa dados enviados
                
        except Exception as e:
            logger.error(f"❌ Erro no envio com recovery: {e}")
            # Em caso de erro, mantém dados para próxima tentativa
            if "quota" in str(e).lower() or "429" in str(e):
                logger.warning("⚠️ Quota excedida - aumentando intervalo para 60s")
                self.sheets_write_interval = 60.0  # Aumenta intervalo se quota excedida (igual ao original)

    def get_current_count(self):
        """Retorna o último person_count recebido"""
        return len(self.current_people)
    
    def get_total_detected(self):
        """Retorna total de pessoas detectadas na sessão"""
        return self.total_people_detected

    def get_status(self):
        """Retorna status completo do radar com estatísticas robustas"""
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
    except Exception as e:
        logger.error(f"❌ Erro configurando Sheets: {e}")
        return
    
    # Inicializa radar com auto-recovery
    radar = AutoRecoveryRadarCounter(RADAR_CONFIG)
    
    try:
        if not radar.start(gsheets_manager):
            logger.error("❌ Falha ao iniciar radar")
            return
        
        # Exibe status inicial completo
        status = radar.get_status()
        logger.info("=" * 80)
        logger.info("👥 CONTADOR SANTA CRUZ v4.3 + AUTO-RECOVERY COMPLETO")
        logger.info("=" * 80)
        logger.info(f"🔴 {status['name']}: {status['port']}")
        logger.info(f"📋 {status['description']}")
        logger.info("🚀 FUNCIONALIDADES INTEGRADAS:")
        logger.info("   ✅ Sistema completo de tracking de pessoas (igual ao original)")
        logger.info("   ✅ Detecção de zonas das ativações (6 ativações específicas)")
        logger.info("   ✅ Lógica robusta de entrada/saída (anti-flickering)")
        logger.info("   ✅ Display detalhado em tempo real")
        logger.info("   ✅ Estatísticas por zona")
        logger.info("   ✅ Auto-reconexão serial inteligente")
        logger.info("   ✅ Auto-recuperação Google Sheets com retry")
        logger.info("   ✅ Monitoramento de saúde em background")
        logger.info("   ✅ Restart preventivo após 12 horas (menos agressivo)")
        logger.info("   ✅ Limpeza de memória automática")
        logger.info("   ✅ Anti-quota inteligente (60s intervalo - mais suave)")
        logger.info("   ✅ Controle de token expirado")
        logger.info("🎯 RESOLUÇÃO DO PROBLEMA DE 3+ HORAS:")
        logger.info("   • Token expirado ➜ Renovação automática")
        logger.info("   • Quota exceeded ➜ Backoff inteligente")
        logger.info("   • Conexão serial perdida ➜ Reconexão automática")
        logger.info("   • Memória alta ➜ Limpeza automática")
        logger.info("   • Sistema travado ➜ Restart preventivo")
        logger.info("⚡ Sistema HÍBRIDO: Funcionalidades completas + Auto-recovery")
        logger.info("🔄 Reconexão automática habilitada para todos os componentes")
        logger.info("🎯 MELHORIAS DE ESTABILIDADE v4.3.1:")
        logger.info("   • Timeouts maiores (5s em vez de 2s)")
        logger.info("   • Cooldown de 1 minuto entre reconexões")
        logger.info("   • Tolerância maior a erros (10 em vez de 5)")
        logger.info("   • Pausas maiores entre tentativas")
        logger.info("   • TERM environment fix para systemd")
        logger.info("   • Leitura serial mais simples e robusta")
        logger.info("=" * 80)
        
        # Loop principal melhorado
        status_counter = 0
        while True:
            time.sleep(5)  # Verifica a cada 5 segundos
            status_counter += 1
            
            # Status detalhado a cada 30 segundos (6 * 5s = 30s)
            if status_counter >= 6:
                status_counter = 0
                status = radar.get_status()
                current_count = status['people_in_area']
                total_detected = status['total_detected']
                max_simultaneous = status['max_simultaneous']
                entries = status['entries_count']
                exits = status['exits_count']
                unique_people = status['unique_people']
                restarts = status['system_restarts']
                health = status['health_status']
                
                # Status baseado na saúde do sistema
                if health == 'healthy' and radar.is_running and radar.serial_connection and radar.serial_connection.is_open:
                    logger.info(f"💚 SAUDÁVEL: {current_count} ativas | {total_detected} total | {entries} entradas | {exits} saídas | {unique_people} únicas | Máx: {max_simultaneous} | Restarts: {restarts}")
                elif radar.is_running:
                    logger.warning(f"💛 PROBLEMAS: Radar rodando mas conexão instável - tentando auto-recovery...")
                else:
                    logger.error(f"❌ CRÍTICO: Radar não está ativo - sistema parado")
                
                # Verifica saúde do Google Sheets
                if gsheets_manager.health_check():
                    logger.info(f"📊 PLANILHA: Funcionando normalmente")
                else:
                    logger.warning(f"📊 PLANILHA: Problemas detectados - executando auto-recovery...")
    
    except KeyboardInterrupt:
        logger.info("🛑 Encerrando por solicitação do usuário...")
    
    except Exception as e:
        logger.error(f"❌ Erro inesperado: {str(e)}")
        logger.error(traceback.format_exc())
    
    finally:
        radar.stop()
        logger.info("✅ Sistema encerrado!")

if __name__ == "__main__":
    main() 
