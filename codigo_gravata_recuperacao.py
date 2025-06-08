#!/usr/bin/env python3
"""
Sistema DUAL RADAR - GRAVATÁ + AUTO-RECUPERAÇÃO
Baseado no Santa Cruz com sistema completo de auto-recuperação
Duas áreas (interna + externa) → Planilhas separadas + Auto-recovery
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
        logging.FileHandler('gravata_dual_auto_recovery.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('gravata_dual_auto_recovery')

# Configurando o nível de log para outros módulos
logging.getLogger('urllib3').setLevel(logging.WARNING)
logging.getLogger('gspread').setLevel(logging.WARNING)

load_dotenv()

# ✅ CONFIGURAÇÃO DOS DOIS RADARES PARA GRAVATÁ - PLANILHAS SEPARADAS
RADAR_CONFIGS = [
    {
        'id': 'RADAR_GRAVATA_EXTERNO',
        'name': 'Contador Gravatá Externo',
        'port': '/dev/ttyACM0',
        'baudrate': 115200,
        'spreadsheet_id': '17KkL1rm1pCJ1Q57FAzyZKqR0lQyPqdiqCjO1mf1QKGQ',  # ✅ Planilha externa correta
        'color': '🔴',
        'area_tipo': 'EXTERNA',
        'description': 'Gravatá Externa: multi-pessoa simultânea, 8.3Hz, até 8 pessoas'
    },
    {
        'id': 'RADAR_GRAVATA_INTERNO',
        'name': 'Contador Gravatá Interno',
        'port': '/dev/ttyACM1', 
        'baudrate': 115200,
        'spreadsheet_id': '1ACu8Qmicxv7Av-1nAK_dIDbcD_RJBizk2iXspixK2Gg',  # ✅ Planilha específica para INTERNA
        'color': '🔵',
        'area_tipo': 'INTERNA',
        'description': 'Gravatá Interna: multi-pessoa simultânea, 8.3Hz, até 8 pessoas'
    }
]

# Configurações gerais
CREDENTIALS_FILE = 'serial_radar/credenciais.json'

class AutoRecoveryGoogleSheetsManager:
    """GoogleSheetsManager com auto-recuperação integrada para Gravatá"""
    
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
                
                logger.info(f"✅ Google Sheets Gravatá conectado (tentativa {attempt + 1})")
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
    def __init__(self, area_tipo):
        self.area_tipo = area_tipo
        
        # Configuração baseada no tipo de área
        if area_tipo == 'EXTERNA':
            # Área externa: apenas 2 zonas simples baseadas na distância
            self.ZONA_CONFIGS = {
                'AREA_INTERESSE': {
                    'x_min': -4.0, 'x_max': 4.0,
                    'y_min': 0.0, 'y_max': 8.0,
                    'distance_range': (0.3, 4.0)  # Perto = área de interesse
                },
                'AREA_PASSAGEM': {
                    'x_min': -4.0, 'x_max': 4.0,
                    'y_min': 0.0, 'y_max': 8.0,
                    'distance_range': (4.0, 8.0)  # Afastado = área de passagem
                }
            }
        else:  # INTERNA
            # ✅ ÁREA INTERNA: EXPANDIDA para capturar melhor as ativações
            self.ZONA_CONFIGS = {
                # LADO ESQUERDO (X < -0.8) - Expandido
                'SALA_REBOCO': {
                    'x_min': -4.0, 'x_max': -0.8,
                    'y_min': 0.2, 'y_max': 4.0,
                    'distance_range': (0.8, 5.0)  # ✅ Range expandido
                },
                'IGREJINHA': {
                    'x_min': -4.0, 'x_max': -0.8,
                    'y_min': 2.0, 'y_max': 7.0,
                    'distance_range': (2.0, 8.0)  # ✅ Range expandido
                },
                
                # LADO DIREITO (X > 0.8) - Expandido
                'BEIJO': {
                    'x_min': 0.8, 'x_max': 4.0,
                    'y_min': 0.5, 'y_max': 5.0,
                    'distance_range': (1.0, 6.0)  # ✅ Range expandido
                },
                'PESCARIA': {
                    'x_min': 0.8, 'x_max': 5.0,
                    'y_min': 0.2, 'y_max': 4.0,
                    'distance_range': (2.0, 7.0)  # ✅ Range expandido
                },
                'ARGOLA': {
                    'x_min': 0.8, 'x_max': 4.0,
                    'y_min': 3.0, 'y_max': 8.0,
                    'distance_range': (3.0, 9.0)  # ✅ Range expandido
                },
                
                # CENTRO - Apenas para posições muito centrais
                'CENTRO': {
                    'x_min': -0.8, 'x_max': 0.8,
                    'y_min': 0.5, 'y_max': 2.5,
                    'distance_range': (0.3, 2.5)  # ✅ Restrito apenas para muito perto
                }
            }
        
    def get_zone(self, x, y):
        """Determinar zona MELHORADA - prioriza posição X e distância"""
        distance = self.get_distance(x, y)
        
        # Debug temporário para mostrar teste de zonas
        debug_info = []
        
        if self.area_tipo == 'EXTERNA':
            # Área externa: verifica posição e distância
            for zona_name, config in self.ZONA_CONFIGS.items():
                if (config['x_min'] <= x <= config['x_max'] and
                    config['y_min'] <= y <= config['y_max'] and
                    config['distance_range'][0] <= distance <= config['distance_range'][1]):
                    return zona_name
            
            # Fallback baseado na distância
            if distance <= 3.5:
                return 'AREA_INTERESSE'
            else:
                return 'AREA_PASSAGEM'
        
        else:  # INTERNA - LÓGICA MELHORADA
            # ✅ PRIMEIRO: Testa todas as zonas específicas
            for zona_name, config in self.ZONA_CONFIGS.items():
                x_ok = config['x_min'] <= x <= config['x_max']
                y_ok = config['y_min'] <= y <= config['y_max']
                dist_ok = config['distance_range'][0] <= distance <= config['distance_range'][1]
                
                debug_info.append(f"{zona_name}: X({x_ok}) Y({y_ok}) D({dist_ok})")
                
                if x_ok and y_ok and dist_ok:
                    logger.info(f"🎯 ZONA ENCONTRADA por configuração específica: {zona_name}")
                    logger.info(f"   Testes: {' | '.join(debug_info)}")
                    return zona_name
            
            # ✅ SEGUNDO: Fallback baseado PRINCIPALMENTE na posição X e distância
            logger.info(f"🔄 FALLBACK ATIVADO - Nenhuma zona específica encontrada")
            logger.info(f"   Testes realizados: {' | '.join(debug_info)}")
            
            if x < -0.8:  # LADO ESQUERDO
                logger.info(f"📍 FALLBACK: LADO ESQUERDO (X={x:.2f} < -0.8)")
                if distance <= 3.0:
                    logger.info(f"   ✅ Distância {distance:.2f}m ≤ 3.0m → SALA_REBOCO")
                    return 'SALA_REBOCO'
                elif distance <= 7.0:
                    logger.info(f"   ✅ Distância {distance:.2f}m ≤ 7.0m → IGREJINHA")
                    return 'IGREJINHA'
                else:
                    logger.info(f"   ❌ Distância {distance:.2f}m > 7.0m → FORA_ATIVACOES")
                    return 'FORA_ATIVACOES'
                    
            elif x > 0.8:  # LADO DIREITO
                logger.info(f"📍 FALLBACK: LADO DIREITO (X={x:.2f} > 0.8)")
                if distance <= 2.5:
                    logger.info(f"   ✅ Distância {distance:.2f}m ≤ 2.5m → BEIJO")
                    return 'BEIJO'
                elif distance <= 5.0:
                    logger.info(f"   ✅ Distância {distance:.2f}m ≤ 5.0m → PESCARIA")
                    return 'PESCARIA'
                elif distance <= 8.0:
                    logger.info(f"   ✅ Distância {distance:.2f}m ≤ 8.0m → ARGOLA")
                    return 'ARGOLA'
                else:
                    logger.info(f"   ❌ Distância {distance:.2f}m > 8.0m → FORA_ATIVACOES")
                    return 'FORA_ATIVACOES'
                    
            else:  # CENTRO (-0.8 <= X <= 0.8)
                logger.info(f"📍 FALLBACK: ZONA CENTRAL (-0.8 ≤ X={x:.2f} ≤ 0.8)")
                if distance <= 1.5:
                    logger.info(f"   ✅ Distância {distance:.2f}m ≤ 1.5m → CENTRO")
                    return 'CENTRO'  # Só muito próximo é centro
                elif distance <= 4.0:
                    # Baseado em Y para decidir se vai para lado esquerdo ou direito
                    if y > 2.5:
                        result = 'IGREJINHA' if x < 0 else 'ARGOLA'
                        logger.info(f"   ✅ Y={y:.2f} > 2.5, X={'<0' if x<0 else '≥0'} → {result}")
                        return result
                    else:
                        result = 'SALA_REBOCO' if x < 0 else 'BEIJO'
                        logger.info(f"   ✅ Y={y:.2f} ≤ 2.5, X={'<0' if x<0 else '≥0'} → {result}")
                        return result
                else:
                    logger.info(f"   ❌ Distância {distance:.2f}m > 4.0m → FORA_ATIVACOES")
                    return 'FORA_ATIVACOES'
    
    def get_distance(self, x, y):
        """Calcular distância do radar"""
        import math
        return math.sqrt(x**2 + y**2)
    
    def get_zone_description(self, zone_name):
        """Retorna descrição amigável da zona"""
        descriptions = {
            # Área externa (2 zonas simples)
            'AREA_INTERESSE': 'Área de Interesse',
            'AREA_PASSAGEM': 'Área de Passagem',
            # ✅ Área interna (IGUAL AO SANTA CRUZ)
            'SALA_REBOCO': 'Sala de Reboco',
            'IGREJINHA': 'Igrejinha', 
            'CENTRO': 'Centro',
            'ARGOLA': 'Jogo da Argola',
            'BEIJO': 'Barraca do Beijo',
            'PESCARIA': 'Pescaria',
            'FORA_ATIVACOES': 'Fora das Ativações'
        }
        return descriptions.get(zone_name, zone_name)

class AutoRecoverySingleRadarCounter:
    """Contador de Radar ÚNICO com sistema de auto-recuperação integrado para Gravatá"""
    
    def __init__(self, config):
        self.config = config
        self.radar_id = config['id']
        self.radar_name = config['name']
        self.area_tipo = config['area_tipo']
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
        self.zone_manager = ZoneManager(self.area_tipo)
        
        # Sistema robusto de contagem de pessoas (igual ao Santa Cruz)
        self.current_people = {}
        self.previous_people = {}
        self.people_history = {}
        self.total_people_detected = 0
        self.max_simultaneous_people = 0
        self.session_start_time = datetime.now()
        
        # Configurações de tracking (mais realistas para pessoas paradas)
        self.exit_timeout = 30.0          # 30 segundos para considerar que saiu (pessoas podem ficar paradas)
        self.reentry_timeout = 10.0
        self.last_update_time = time.time()
        self.person_timeout = 30.0         # Timeout principal para pessoas inativas
        
        # Configurações anti-quota (intervalos maiores para melhor detecção)
        self.last_sheets_write = 0
        self.sheets_write_interval = 180.0  # 3 minutos para evitar quota
        self.pending_data = []
        
        # Estatísticas detalhadas
        self.entries_count = 0
        self.exits_count = 0
        self.unique_people_today = set()
        
        # Thread de monitoramento
        self.monitoring_thread = None
        
        # Controle de estabilidade
        self.last_connection_attempt = datetime.now() - timedelta(minutes=10)
        self.connection_cooldown = 60  # 1 minuto entre tentativas
        self.consecutive_connection_failures = 0
        self.max_connection_failures = 5
    
    def start_health_monitoring(self):
        """Inicia monitoramento de saúde em background"""
        self.monitoring_thread = threading.Thread(target=self._health_monitoring_loop, daemon=True)
        self.monitoring_thread.start()
        logger.info(f"{self.color} 🔄 Monitoramento de saúde iniciado")
        
    def _health_monitoring_loop(self):
        """Loop de monitoramento de saúde"""
        while self.is_running:
            try:
                time.sleep(60)  # Verifica a cada minuto
                self._check_system_health()
            except Exception as e:
                logger.error(f"{self.color} ❌ Erro no monitoramento: {e}")
                time.sleep(30)
                
    def _check_system_health(self):
        """Verifica saúde geral do sistema (mais suave)"""
        now = datetime.now()
        
        # 1. Verifica recebimento de dados serial (mais tolerante)
        time_since_data = now - self.last_data_received
        if time_since_data > timedelta(minutes=10):  # 10 minutos em vez de 5
            logger.warning(f"{self.color} ⚠️ Sem dados seriais há {time_since_data}")
            if self._should_attempt_recovery():
                self._attempt_serial_recovery()
        
        # 2. Verifica envios para planilha (menos frequente)
        time_since_sheets = now - self.last_sheets_success
        if time_since_sheets > timedelta(minutes=20):  # 20 minutos em vez de 10
            logger.warning(f"{self.color} ⚠️ Sem envios há {time_since_sheets}")
            if self.gsheets_manager and self._should_attempt_recovery():
                self.gsheets_manager._attempt_full_recovery()
        
        # 3. Verifica uso de memória
        try:
            import psutil
            process = psutil.Process()
            memory_mb = process.memory_info().rss / 1024 / 1024
            
            if memory_mb > 200:  # 200MB limite
                logger.warning(f"{self.color} ⚠️ Memória alta: {memory_mb:.1f}MB")
                self._cleanup_memory()
                
        except ImportError:
            pass  # psutil não disponível
        except Exception as e:
            logger.debug(f"Erro verificando memória: {e}")
        
        # 4. Restart preventivo após 12 horas (menos agressivo)
        runtime = now - self.start_time
        if runtime > timedelta(hours=12):  # 12 horas em vez de 6
            logger.info(f"{self.color} ⏰ Runtime {runtime} - restart preventivo recomendado")
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
                logger.info(f"{self.color} 🧹 Buffer limpo")
            
            # Força garbage collection
            gc.collect()
            
        except Exception as e:
            logger.error(f"{self.color} ❌ Erro limpando memória: {e}")
    
    def _attempt_serial_recovery(self):
        """Tenta recuperar conexão serial (mais suave)"""
        try:
            self.consecutive_connection_failures += 1
            
            if self.consecutive_connection_failures > self.max_connection_failures:
                logger.warning(f"{self.color} ⚠️ Muitas falhas consecutivas ({self.consecutive_connection_failures}) - pausando 5 minutos")
                time.sleep(300)  # 5 minutos de pausa
                self.consecutive_connection_failures = 0
            
            logger.info(f"{self.color} 🔄 Tentando recuperar conexão serial (tentativa {self.consecutive_connection_failures})...")
            
            # Fecha conexão atual com pausa maior
            if self.serial_connection:
                try:
                    self.serial_connection.close()
                except:
                    pass
                time.sleep(5)  # 5 segundos em vez de 2
            
            # Tenta reconectar
            if self.connect():
                logger.info(f"{self.color} ✅ Conexão serial recuperada!")
                self.consecutive_connection_failures = 0
                return True
            else:
                logger.error(f"{self.color} ❌ Falha na recuperação serial (tentativa {self.consecutive_connection_failures})")
                time.sleep(10)  # Pausa antes da próxima tentativa
                return False
                
        except Exception as e:
            logger.error(f"{self.color} ❌ Erro na recuperação serial: {e}")
            return False
    
    def _attempt_system_restart(self):
        """Restart preventivo do sistema"""
        if self.system_restart_count >= self.max_system_restarts:
            logger.error(f"{self.color} 🚨 Máximo de restarts atingido")
            return False
            
        self.system_restart_count += 1
        logger.info(f"{self.color} 🔄 Restart preventivo #{self.system_restart_count}")
        
        try:
            # Para sistema
            self.stop()
            time.sleep(5)
            
            # Re-inicializa
            self.start_with_existing_manager()
            
            # Reset contadores
            self.start_time = datetime.now()
            
            logger.info(f"{self.color} ✅ Restart preventivo concluído")
            return True
            
        except Exception as e:
            logger.error(f"{self.color} ❌ Falha no restart preventivo: {e}")
            return False

    def find_serial_port(self):
        """Detecta automaticamente a porta serial"""
        ports = list(serial.tools.list_ports.comports())
        if not ports:
            logger.error("Nenhuma porta serial encontrada!")
            return None
        
        logger.info(f"🔍 Portas seriais disponíveis:")
        for port in ports:
            logger.info(f"   📡 {port.device} - {port.description}")
        
        # Primeiro tenta a porta configurada
        for port in ports:
            if port.device == self.port:
                logger.info(f"✅ Porta configurada encontrada: {self.port}")
                return self.port
        
        # Se não encontrou, procura por dispositivos apropriados
        for port in ports:
            desc_lower = port.description.lower()
            if any(term in desc_lower for term in
                  ['usb', 'serial', 'uart', 'cp210', 'ch340', 'ft232', 'arduino', 'esp32', 'jtag', 'modem']):
                logger.warning(f"Porta {self.port} não encontrada, tentando usar {port.device}")
                return port.device
        
        logger.error("Nenhuma porta adequada encontrada!")
        return None

    def connect(self):
        """Conecta à porta serial com reconexão automática"""
        max_attempts = 3
        
        for attempt in range(max_attempts):
            try:
                # Verifica se a porta ainda existe
                if not os.path.exists(self.port):
                    logger.warning(f"{self.color} Porta {self.port} não existe mais, detectando nova porta...")
                    detected_port = self.find_serial_port()
                    if detected_port:
                        self.port = detected_port
                    else:
                        logger.error(f"{self.color} Tentativa {attempt + 1}/{max_attempts}: Nenhuma porta encontrada")
                        time.sleep(2)
                        continue
                
                # Fecha conexão anterior se existir
                if hasattr(self, 'serial_connection') and self.serial_connection:
                    try:
                        self.serial_connection.close()
                    except:
                        pass
                
                logger.info(f"{self.color} Tentativa {attempt + 1}/{max_attempts}: Conectando à porta {self.port}...")
                
                self.serial_connection = serial.Serial(
                    port=self.port,
                    baudrate=self.baudrate,
                    timeout=2,
                    write_timeout=2,
                    bytesize=serial.EIGHTBITS,
                    parity=serial.PARITY_NONE,
                    stopbits=serial.STOPBITS_ONE
                )
                
                # Aguarda estabilização
                time.sleep(3)
                
                # Testa a conexão
                if self.serial_connection.is_open:
                    logger.info(f"{self.color} ✅ Conexão estabelecida com sucesso!")
                    return True
                else:
                    logger.warning(f"{self.color} ⚠️ Porta aberta mas não está responsiva")
                    
            except serial.SerialException as e:
                logger.error(f"{self.color} ❌ Erro serial na tentativa {attempt + 1}: {str(e)}")
            except Exception as e:
                logger.error(f"{self.color} ❌ Erro geral na tentativa {attempt + 1}: {str(e)}")
            
            if attempt < max_attempts - 1:
                wait_time = (attempt + 1) * 2
                logger.info(f"{self.color} ⏳ Aguardando {wait_time}s antes da próxima tentativa...")
                time.sleep(wait_time)
        
        logger.error(f"{self.color} ❌ Falha ao conectar após {max_attempts} tentativas")
        return False

    def start(self, gsheets_manager):
        """Inicia o radar (método original)"""
        self.gsheets_manager = gsheets_manager
        
        if not self.connect():
            return False
        
        self.is_running = True
        self.receive_thread = threading.Thread(target=self.receive_data_loop, daemon=True)
        self.receive_thread.start()
        
        logger.info(f"{self.color} 🚀 Radar {self.area_tipo} iniciado com sucesso!")
        return True

    def start_with_existing_manager(self):
        """✅ Inicia o radar usando gsheets_manager já configurado com auto-recuperação"""
        if not self.gsheets_manager:
            logger.error(f"{self.color} ❌ GoogleSheetsManager não configurado para {self.area_tipo}")
            return False
        
        if not self.connect():
            return False
        
        self.is_running = True
        self.receive_thread = threading.Thread(target=self.receive_data_loop, daemon=True)
        self.receive_thread.start()
        
        # Inicia monitoramento de saúde
        self.start_health_monitoring()
        
        logger.info(f"{self.color} 🚀 Radar {self.area_tipo} iniciado com auto-recuperação!")
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
        
        logger.info(f"{self.color} 🛑 Radar {self.area_tipo} parado!")

    def receive_data_loop(self):
        """Loop de dados com auto-recuperação (mais estável)"""
        buffer = ""
        consecutive_errors = 0
        max_consecutive_errors = 10  # Mais tolerante
        
        while self.is_running:
            try:
                if not self.serial_connection or not self.serial_connection.is_open:
                    logger.warning(f"{self.color} ⚠️ Conexão perdida, tentando reconectar...")
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
                
                # Limpeza periódica de pessoas inativas
                current_time = time.time()
                if not hasattr(self, 'last_cleanup_time'):
                    self.last_cleanup_time = current_time
                elif current_time - self.last_cleanup_time > 30.0:  # A cada 30 segundos
                    self.cleanup_inactive_people()
                    self.last_cleanup_time = current_time
                
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
                    logger.error(f"{self.color} ⚠️ Outra aplicação está usando a porta - aguardando...")
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
        """Converte timestamp de milissegundos para formato brasileiro"""
        try:
            if timestamp_ms and timestamp_ms > 0:
                # Converte milissegundos para segundos e cria datetime
                timestamp_seconds = timestamp_ms / 1000.0
                dt = datetime.fromtimestamp(timestamp_seconds)
                return dt.strftime('%d/%m/%Y %H:%M:%S')
            else:
                # Fallback para horário atual se timestamp inválido
                dt = datetime.now()
                return dt.strftime('%d/%m/%Y %H:%M:%S')
        except Exception as e:
            logger.debug(f"Erro na conversão de timestamp {timestamp_ms}: {e}")
            # Fallback para horário atual
            return datetime.now().strftime('%d/%m/%Y %H:%M:%S')

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
        """Sistema CORRIGIDO de tracking para eventos - lógica precisa de entrada/saída"""
        current_time = time.time()
        
        current_people_dict = {}
        
        for i, person in enumerate(active_people):
            x_pos = person.get('x_pos', 0)
            y_pos = person.get('y_pos', 0) 
            
            # 🔍 DEBUG: Verifica campos de distância disponíveis
            distance_raw = person.get('distance_raw', None)
            distance_smoothed = person.get('distance_smoothed', None)
            
            # Debug detalhado dos dados recebidos
            logger.info(f"🔍 DEBUG {self.area_tipo} Pessoa {i}: campos recebidos do Arduino:")
            logger.info(f"   distance_raw: {distance_raw}")
            logger.info(f"   distance_smoothed: {distance_smoothed}")
            logger.info(f"   x_pos: {x_pos}, y_pos: {y_pos}")
            logger.info(f"   outros campos: {list(person.keys())}")
            
            # SEMPRE CALCULA DISTÂNCIA DAS COORDENADAS (mais confiável)
            import math
            calculated_distance = math.sqrt(x_pos**2 + y_pos**2)
            
            # Usa distância calculada como padrão, comparando com Arduino
            distance = calculated_distance
            
            # Se Arduino enviou distância, compara
            arduino_distance = distance_smoothed if distance_smoothed is not None else distance_raw
            if arduino_distance is not None and arduino_distance > 0:
                if abs(arduino_distance - calculated_distance) < 0.3:
                    # Arduino está consistente, pode usar
                    distance = arduino_distance
                    logger.info(f"   ✅ Arduino consistente: {arduino_distance:.2f}m (calculada: {calculated_distance:.2f}m)")
                else:
                    # Arduino suspeito, usa calculada
                    logger.warning(f"   ⚠️ Arduino suspeito: {arduino_distance:.2f}m vs calculada: {calculated_distance:.2f}m - USANDO CALCULADA")
            else:
                logger.info(f"   🔧 Arduino sem distância, usando calculada: {distance:.2f}m")
            
            # ✅ CALCULA ZONA ESPECÍFICA DA ÁREA usando coordenadas x,y
            zone = self.zone_manager.get_zone(x_pos, y_pos)
            person["zone"] = zone  # Atualiza o objeto pessoa com a zona correta
            
            # ID baseado na posição arredondada (estável para pessoa parada)
            stable_id = f"P_{self.area_tipo}_{zone}_{distance:.1f}_{i}"
            
            # Procura se já existe pessoa similar (mesma zona, distância similar)
            found_existing = None
            for existing_id, existing_person in self.current_people.items():
                existing_dist = existing_person.get('distance_smoothed')
                if existing_dist is None:
                    existing_dist = existing_person.get('distance_raw')
                if existing_dist is None:
                    # Calcula das coordenadas se não tem distância
                    existing_x = existing_person.get('x_pos', 0)
                    existing_y = existing_person.get('y_pos', 0)
                    existing_dist = math.sqrt(existing_x**2 + existing_y**2)
                    
                existing_zone = existing_person.get('zone', '')
                
                if (existing_zone == zone and 
                    abs(existing_dist - distance) < 0.3):
                    found_existing = existing_id
                    break
            
            if found_existing:
                current_people_dict[found_existing] = person
                current_people_dict[found_existing]['last_seen'] = current_time
            else:
                person['first_seen'] = current_time
                person['last_seen'] = current_time
                current_people_dict[stable_id] = person
        
        # Detecta ENTRADAS REAIS
        new_entries = []
        for person_id, person_info in current_people_dict.items():
            if person_id not in self.current_people:
                is_really_new = True
                for old_id, old_person in self.previous_people.items():
                    old_zone = old_person.get('zone', '')
                    old_dist = old_person.get('distance_smoothed')
                    if old_dist is None:
                        old_dist = old_person.get('distance_raw')
                    if old_dist is None:
                        old_x = old_person.get('x_pos', 0)
                        old_y = old_person.get('y_pos', 0)
                        old_dist = math.sqrt(old_x**2 + old_y**2)
                        
                    new_zone = person_info.get('zone', '')
                    new_dist = person_info.get('distance_smoothed')
                    if new_dist is None:
                        new_dist = person_info.get('distance_raw')
                    if new_dist is None:
                        new_x = person_info.get('x_pos', 0)
                        new_y = person_info.get('y_pos', 0)
                        new_dist = math.sqrt(new_x**2 + new_y**2)
                    
                    if (old_zone == new_zone and 
                        abs(old_dist - new_dist) < 0.5 and
                        (current_time - old_person.get('last_seen', 0)) < 2.0):
                        is_really_new = False
                        break
                
                if is_really_new:
                    new_entries.append(person_id)
                    self.total_people_detected += 1
                    self.entries_count += 1
                    self.unique_people_today.add(person_id)
                    zone = person_info.get('zone', 'DESCONHECIDA')
                    dist = person_info.get('distance_smoothed', 0)
                    logger.info(f"🆕 ENTRADA {self.area_tipo}: {zone} {dist:.1f}m (Total: {self.total_people_detected})")
        
        # Detecta SAÍDAS REAIS
        exits = []
        for person_id, person_info in self.current_people.items():
            if person_id not in current_people_dict:
                last_seen = person_info.get('last_seen', 0)
                if (current_time - last_seen) > self.person_timeout:
                    exits.append(person_id)
                    self.exits_count += 1
                    zone = person_info.get('zone', 'DESCONHECIDA')
                    dist = person_info.get('distance_smoothed', 0)
                    logger.info(f"🚪 SAÍDA {self.area_tipo}: {zone} {dist:.1f}m")
        
        # Atualiza estado
        self.previous_people = self.current_people.copy()
        self.current_people = current_people_dict
        
        # Atualiza máximo simultâneo
        current_simultaneous = len(current_people_dict)
        if current_simultaneous > self.max_simultaneous_people:
            self.max_simultaneous_people = current_simultaneous
            logger.info(f"📊 NOVO MÁXIMO {self.area_tipo}: {self.max_simultaneous_people} pessoas")
        
        self.last_update_time = current_time

    def cleanup_inactive_people(self):
        """Remove pessoas que não foram vistas há muito tempo"""
        current_time = time.time()
        to_remove = []
        
        for person_id, person_info in self.current_people.items():
            last_seen = person_info.get('last_seen', 0)
            if (current_time - last_seen) > self.person_timeout:
                to_remove.append(person_id)
                zone = person_info.get('zone', 'DESCONHECIDA')
                logger.info(f"🧹 Limpeza {self.area_tipo}: removendo {person_id} de {zone} após {self.person_timeout}s")
        
        for person_id in to_remove:
            del self.current_people[person_id]

    def process_json_data(self, data_json):
        """Processa dados JSON IGUAL AO SANTA CRUZ com área específica"""
        try:
            # 🔍 DEBUG: Mostra JSON completo recebido do Arduino
            logger.info(f"🔍 JSON COMPLETO {self.area_tipo}: {data_json}")
            
            radar_id = data_json.get("radar_id", self.radar_id)
            timestamp_ms = data_json.get("timestamp_ms", 0)
            person_count = data_json.get("person_count", 0)
            active_people = data_json.get("active_people", [])
            
            # Debug dos campos principais
            logger.info(f"🔍 CAMPOS PRINCIPAIS {self.area_tipo}:")
            logger.info(f"   radar_id: {radar_id}")
            logger.info(f"   timestamp_ms: {timestamp_ms}")
            logger.info(f"   person_count: {person_count}")
            logger.info(f"   active_people count: {len(active_people)}")

            formatted_timestamp = self.convert_timestamp(timestamp_ms)
            logger.info(f"🔍 TIMESTAMP {self.area_tipo}: {timestamp_ms}ms → {formatted_timestamp}")

            # Atualiza contadores locais
            self.update_people_count(person_count, active_people)

            # ✅ LIMPA TERMINAL IGUAL AO SANTA CRUZ (apenas aqui)
            os.system('clear')

            # ✅ DISPLAY IGUAL AO SANTA CRUZ + área específica
            print(f"\n{self.color} ═══ GRAVATÁ {self.area_tipo} - TRACKING AVANÇADO ═══")
            print(f"⏰ {formatted_timestamp}")
            print(f"📡 {radar_id} | 👥 ATIVAS: {person_count}")
            print(f"🎯 TOTAL DETECTADAS: {self.total_people_detected} | 📊 MÁXIMO SIMULTÂNEO: {self.max_simultaneous_people}")
            print(f"🔄 ENTRADAS: {self.entries_count} | 🚪 SAÍDAS: {self.exits_count}")
            print(f"🆔 PESSOAS ÚNICAS: {len(self.unique_people_today)}")

            # Mostra duração da sessão (igual Santa Cruz)
            session_duration = datetime.now() - self.session_start_time
            duration_str = self.format_duration(session_duration.total_seconds() * 1000)
            print(f"⏱️ SESSÃO: {duration_str}")

            # ✅ STATUS DO ENVIO IGUAL AO SANTA CRUZ
            pending_count = len(self.pending_data)
            time_since_last_send = time.time() - self.last_sheets_write
            next_send_in = max(0, self.sheets_write_interval - time_since_last_send)
            if pending_count > 0:
                print(f"📋 BUFFER: {pending_count} linhas | ⏳ Próximo envio em: {next_send_in:.0f}s")
            else:
                print(f"📋 PLANILHA: Sincronizada ✅")

            if active_people and len(active_people) > 0:
                # ✅ TABELA COM DEBUG DE COORDENADAS
                print(f"\n👥 PESSOAS DETECTADAS AGORA ({len(active_people)}):")
                if self.area_tipo == 'INTERNA':
                    print(f"{'Ativação':<15} {'Dist(m)':<7} {'X,Y':<12} {'Conf%':<5} {'Status':<8} {'Desde':<8}")
                else:
                    print(f"{'Zona':<15} {'Dist(m)':<7} {'X,Y':<12} {'Conf%':<5} {'Status':<8} {'Desde':<8}")
                print("-" * 70)

                current_time = time.time()
                for i, person in enumerate(active_people):
                    confidence = person.get("confidence", 0)
                    
                    # 🔍 DEBUG: Examina campos de distância mais detalhadamente
                    distance_raw = person.get("distance_raw", None)
                    distance_smoothed = person.get("distance_smoothed", None)
                    distance_final = distance_smoothed if distance_smoothed is not None else distance_raw
                    
                    x_pos = person.get("x_pos", 0)
                    y_pos = person.get("y_pos", 0)
                    stationary = person.get("stationary", False)
                    
                    # Debug de todos os campos recebidos do Arduino
                    logger.info(f"🔍 DISPLAY DEBUG {self.area_tipo} Pessoa {i}:")
                    logger.info(f"   JSON completo: {person}")
                    logger.info(f"   distance_raw: {distance_raw}")
                    logger.info(f"   distance_smoothed: {distance_smoothed}")
                    logger.info(f"   distance_final: {distance_final}")

                    # ✅ CALCULA ZONA MELHORADA (com debug detalhado)
                    zone = self.zone_manager.get_zone(x_pos, y_pos)
                    person["zone"] = zone  # Atualiza o objeto pessoa com a zona correta

                    # 🔍DEBUG DETALHADO: Mostra todo o processo de cálculo
                    calculated_distance = self.zone_manager.get_distance(x_pos, y_pos)
                    logger.info(f"🔍 DEBUG {self.area_tipo}: X={x_pos:.2f}, Y={y_pos:.2f}")
                    logger.info(f"   📏 Distância calculada: {calculated_distance:.2f}m (Arduino raw: {distance_raw}, smoothed: {distance_smoothed})")
                    logger.info(f"   🎯 Zona determinada: {zone}")
                    
                    # Mostra qual lógica foi aplicada
                    if x_pos < -0.8:
                        logger.info(f"   📍 Lógica: LADO ESQUERDO (X < -0.8)")
                    elif x_pos > 0.8:
                        logger.info(f"   📍 Lógica: LADO DIREITO (X > 0.8)")
                    else:
                        logger.info(f"   📍 Lógica: CENTRO (-0.8 ≤ X ≤ 0.8)")

                    # Encontra ID da nossa lógica interna (igual Santa Cruz)
                    our_person_id = None
                    distance_to_compare = distance_final if distance_final is not None else calculated_distance
                    for internal_id, internal_person in self.current_people.items():
                        internal_distance = internal_person.get('distance_smoothed')
                        if internal_distance is None:
                            internal_distance = internal_person.get('distance_raw')
                        if internal_distance is None:
                            # Calcula das coordenadas se não tem distância
                            internal_x = internal_person.get('x_pos', 0)
                            internal_y = internal_person.get('y_pos', 0)
                            internal_distance = math.sqrt(internal_x**2 + internal_y**2)
                        if (abs(internal_distance - distance_to_compare) < 0.1 and
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

                    status = "Parado" if stationary else "Móvel"
                    pos_str = f"{x_pos:.2f},{y_pos:.2f}"  # ✅ Mais precisão nas coordenadas
                    
                    # Usa a distância correta (prioriza calculated se Arduino está dando valores estranhos)
                    display_distance = distance_final if distance_final is not None and distance_final > 0 else calculated_distance

                    zone_desc = self.zone_manager.get_zone_description(zone)[:14]
                    print(f"{zone_desc:<15} {display_distance:<7.2f} {pos_str:<12} {confidence:<5}% {status:<8} {time_str:<8}")
                    
                    # ⚠️ ALERTA se distância do Arduino suspeita
                    if distance_final is not None and abs(distance_final - calculated_distance) > 0.5:
                        logger.warning(f"⚠️ Discrepância de distância: Arduino={distance_final:.2f}m vs Calculada={calculated_distance:.2f}m")

                # ✅ ENVIA DADOS IGUAL AO SANTA CRUZ (formato de 9 campos)
                if self.gsheets_manager:
                    # Calcula dados agregados
                    avg_confidence = sum(p.get("confidence", 0) for p in active_people) / len(active_people)
                    # ✅ COLETA ZONAS JÁ CORRIGIDAS (calculadas pelo ZoneManager)
                    zones_detected = list(set(p.get("zone", "N/A") for p in active_people))
                    zones_str = ",".join(sorted(zones_detected))

                    # ID mais profissional baseado no contexto (igual Santa Cruz)
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

                    # ✅ CALCULA DISTÂNCIA MÉDIA CORRIGIDA
                    valid_distances = []
                    for i, p in enumerate(active_people):
                        distance_raw = p.get('distance_raw', None)
                        distance_smoothed = p.get('distance_smoothed', None)
                        x = p.get('x_pos', 0)
                        y = p.get('y_pos', 0)
                        
                        # 🔍 DEBUG CRÍTICO: Mostra exatamente o que está sendo usado
                        logger.error(f"🔍 PLANILHA DEBUG {self.area_tipo} Pessoa {i}:")
                        logger.error(f"   distance_raw do Arduino: {distance_raw}")
                        logger.error(f"   distance_smoothed do Arduino: {distance_smoothed}")
                        logger.error(f"   x_pos: {x}, y_pos: {y}")
                        
                        # ✅ SEMPRE USA DISTÂNCIA CALCULADA (mais confiável)
                        import math
                        calculated_distance = math.sqrt(x**2 + y**2)
                        distance = calculated_distance  # FORÇA uso da calculada
                        
                        # Log do Arduino só para debug
                        arduino_distance = distance_smoothed if distance_smoothed is not None else distance_raw
                        if arduino_distance is not None and arduino_distance > 0:
                            if abs(arduino_distance - calculated_distance) > 0.3:
                                logger.error(f"   ⚠️ Arduino suspeito: {arduino_distance:.3f}m vs Real: {calculated_distance:.3f}m")
                            else:
                                logger.error(f"   ✅ Arduino consistente: {arduino_distance:.3f}m (usando real: {calculated_distance:.3f}m)")
                        else:
                            logger.error(f"   🔧 Arduino sem distância, usando calculada: {distance:.3f}m")
                        
                        logger.error(f"   📊 DISTÂNCIA REAL PARA PLANILHA: {distance:.3f}m")
                        valid_distances.append(distance)
                    
                    avg_distance = sum(valid_distances) / len(valid_distances) if valid_distances else 0
                    logger.error(f"🔍 DISTÂNCIA MÉDIA PARA PLANILHA {self.area_tipo}: {avg_distance:.3f}m")
                    
                    # ✅ FORMATO SANTA CRUZ (9 campos) - planilha separada por área
                    row = [
                        radar_id,                          # 1. radar_id (simples, cada área tem planilha própria)
                        formatted_timestamp,               # 2. timestamp (CORRIGIDO)
                        len(active_people),                # 3. person_count (real detectadas agora)
                        person_description,                # 4. person_id (descrição profissional)
                        zones_str,                         # 5. zone (todas as zonas ordenadas)
                        f"{avg_distance:.1f}",             # 6. distance (média CORRIGIDA)
                        f"{avg_confidence:.0f}",           # 7. confidence (média)
                        self.total_people_detected,        # 8. total_detected (nossa contagem real)
                        self.max_simultaneous_people       # 9. max_simultaneous (nosso máximo real)
                    ]
                    self.pending_data.append(row)

                print(f"\n💡 DETECTANDO {len(active_people)} pessoa(s) SIMULTANEAMENTE")

                # ✅ ESTATÍSTICAS POR ZONA IGUAL AO SANTA CRUZ
                zone_stats = {}
                high_confidence = 0
                for person in active_people:
                    zone = person.get("zone", "N/A")  # Zona já foi corrigida acima
                    zone_stats[zone] = zone_stats.get(zone, 0) + 1
                    if person.get("confidence", 0) >= 70:
                        high_confidence += 1

                if zone_stats:
                    if self.area_tipo == 'INTERNA':
                        print("📊 DISTRIBUIÇÃO POR ATIVAÇÃO:")
                    else:
                        print("📊 DISTRIBUIÇÃO POR ZONA:")
                    for zone, count in zone_stats.items():
                        zone_desc = self.zone_manager.get_zone_description(zone)
                        print(f"   • {zone_desc}: {count} pessoa(s)")
                    print()

                print(f"✅ QUALIDADE: {high_confidence}/{len(active_people)} com alta confiança (≥70%)")

            else:
                print(f"\n👻 Nenhuma pessoa detectada no momento.")

                # ✅ ENVIA DADOS ZERADOS IGUAL AO SANTA CRUZ
                if self.gsheets_manager and len(self.previous_people) > 0:
                    row = [
                        radar_id,                          # 1. radar_id (simples, cada área tem planilha própria)
                        formatted_timestamp,               # 2. timestamp
                        0,                                 # 3. person_count (zero)
                        "Area_Vazia",                      # 4. person_id (indicador)
                        "VAZIA",                           # 5. zone 
                        "0",                               # 6. distance
                        "0",                               # 7. confidence
                        self.total_people_detected,        # 8. total_detected (nossa contagem real)
                        self.max_simultaneous_people       # 9. max_simultaneous (nosso máximo real)
                    ]
                    self.pending_data.append(row)

            print("\n" + "═" * 60)
            print("🎯 SISTEMA ROBUSTO: Detecta entradas/saídas precisamente")
            print("⚡ Pressione Ctrl+C para encerrar | Tracking Avançado Ativo")

            # ✅ ENVIA COM AUTO-RECOVERY
            self.send_pending_data_with_recovery()

        except Exception as e:
            logger.error(f"Erro ao processar dados JSON {self.area_tipo}: {e}")

    def send_pending_data_with_recovery(self):
        """Envia dados para Google Sheets de forma controlada com auto-recuperação"""
        try:
            current_time = time.time()
            
            # Verifica se já passou tempo suficiente desde último envio
            if (current_time - self.last_sheets_write) < self.sheets_write_interval:
                return  # Ainda não é hora de enviar
            
            # Se não há dados pendentes, não faz nada
            if not self.pending_data or not self.gsheets_manager:
                return
            
            # Pega apenas os dados mais recentes (máximo 10 linhas por vez)
            data_to_send = self.pending_data[-10:] if len(self.pending_data) > 10 else self.pending_data
            
            # Envia em lote (mais eficiente) com auto-recovery
            if data_to_send:
                logger.info(f"📊 Enviando {len(data_to_send)} linhas {self.area_tipo} para Google Sheets com auto-recovery...")
                
                # Envia todas as linhas com retry automático
                for row in data_to_send:
                    success = self.gsheets_manager.append_row_with_auto_recovery(row)
                    if success:
                        self.last_sheets_success = datetime.now()
                    time.sleep(0.5)  # Pequena pausa entre linhas
                
                logger.info(f"✅ {len(data_to_send)} linhas {self.area_tipo} enviadas com auto-recovery!")
                
                # Atualiza controles
                self.last_sheets_write = current_time
                self.pending_data = []  # Limpa dados enviados
                
        except Exception as e:
            logger.error(f"❌ Erro no envio {self.area_tipo} com recovery: {e}")
            # Em caso de erro, mantém dados para próxima tentativa
            if "quota" in str(e).lower() or "429" in str(e):
                logger.warning(f"⚠️ Quota excedida {self.area_tipo} - aumentando intervalo para 60s")
                self.sheets_write_interval = 60.0

    def get_current_count(self):
        return len(self.current_people)
    
    def get_total_detected(self):
        return self.total_people_detected

    def get_status(self):
        """Retorna status completo do radar com estatísticas de auto-recuperação"""
        return {
            'id': self.radar_id,
            'name': self.radar_name,
            'area_tipo': self.area_tipo,
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
            'health_status': 'healthy' if datetime.now() - self.last_data_received < timedelta(minutes=5) else 'unhealthy',
            'last_data_received': self.last_data_received.strftime('%d/%m/%Y %H:%M:%S'),
            'last_sheets_success': self.last_sheets_success.strftime('%d/%m/%Y %H:%M:%S'),
            'consecutive_failures': getattr(self.gsheets_manager, 'consecutive_failures', 0) if self.gsheets_manager else 0
        }

class GravataDualRadarSystem:
    def __init__(self):
        self.radars = []
        self.is_running = False

    def detect_available_ports(self):
        """Detecta portas seriais disponíveis"""
        ports = list(serial.tools.list_ports.comports())
        available_ports = []
        
        logger.info("🔍 Detectando portas seriais...")
        for port in ports:
            logger.info(f"   📡 {port.device} - {port.description}")
            available_ports.append(port.device) 
        
        return available_ports

    def initialize(self):
        """Inicializa o sistema dual radar com planilhas separadas"""
        try:
            # Detecta portas disponíveis
            available_ports = self.detect_available_ports()
            
            if len(available_ports) < 2:
                logger.error(f"❌ Necessário 2 portas, encontradas {len(available_ports)}")
                logger.info("💡 Conecte 2 dispositivos radar antes de prosseguir")
                return False
            
            # Ajusta configurações de porta se necessário
            for i, config in enumerate(RADAR_CONFIGS):
                if config['port'] not in available_ports:
                    if i < len(available_ports):
                        new_port = available_ports[i]
                        logger.warning(f"⚠️ Porta {config['port']} não encontrada, usando {new_port}")
                        config['port'] = new_port
                    else:
                        logger.error(f"❌ Não há portas suficientes para {config['id']}")
                        return False
            
            # ✅ CREDENCIAIS COMPARTILHADAS
            script_dir = os.path.dirname(os.path.abspath(__file__))
            credentials_file = os.path.join(script_dir, CREDENTIALS_FILE)
            
            if not os.path.exists(credentials_file):
                logger.error(f"❌ Credenciais não encontradas: {credentials_file}")
                return False
            
            # ✅ INICIALIZA RADARES COM AUTO-RECUPERAÇÃO E PLANILHAS SEPARADAS
            for config in RADAR_CONFIGS:
                # Cada radar terá seu próprio AutoRecoveryGoogleSheetsManager
                gsheets_manager = AutoRecoveryGoogleSheetsManager(
                    credentials_file,
                    config['spreadsheet_id'],  # ✅ Planilha específica para cada área
                    config['id']
                )
                
                radar = AutoRecoverySingleRadarCounter(config)
                radar.gsheets_manager = gsheets_manager  # ✅ Atribui planilha específica
                self.radars.append(radar)
                
                logger.info(f"✅ {config['area_tipo']}: Auto-Recovery + Planilha {config['spreadsheet_id'][:8]}...")
            
            logger.info("✅ Sistema Dual Radar Gravatá com AUTO-RECUPERAÇÃO inicializado!")
            return True
            
        except Exception as e:
            logger.error(f"❌ Erro na inicialização: {e}")
            return False

    def start(self):
        """Inicia ambos os radares com planilhas separadas"""
        try:
            if not self.radars:
                logger.error("❌ Sistema não inicializado")
                return False
            
            # ✅ Inicia cada radar (já tem gsheets_manager próprio)
            failed_radars = []
            for radar in self.radars:
                if not radar.start_with_existing_manager():  # ✅ Usa manager já configurado
                    failed_radars.append(radar.radar_id)
            
            if failed_radars:
                logger.error(f"❌ Falha ao iniciar radares: {failed_radars}")
                return False
            
            self.is_running = True
            logger.info("🚀 Sistema Dual Radar Gravatá ATIVO com planilhas separadas!")
            return True
            
        except Exception as e:
            logger.error(f"❌ Erro ao iniciar sistema: {e}")
            return False

    def stop(self):
        """Para todos os radares"""
        self.is_running = False
        
        for radar in self.radars:
            radar.stop()
        
        logger.info("🛑 Sistema Dual Radar Gravatá parado!")

    def get_status(self):
        """Status de ambos os radares"""
        status = {
            'system_running': self.is_running,
            'radars': []
        }
        
        for radar in self.radars:
            status['radars'].append(radar.get_status())
        
        return status

def list_available_ports():
    """Lista todas as portas seriais disponíveis"""
    ports = list(serial.tools.list_ports.comports())
    
    print("\n🔍 DIAGNÓSTICO DE PORTAS SERIAIS - GRAVATÁ DUAL")
    print("=" * 60)
    
    if not ports:
        print("❌ Nenhuma porta serial encontrada!")
        return []
    
    print(f"✅ {len(ports)} porta(s) encontrada(s):")
    
    for i, port in enumerate(ports, 1):
        print(f"\n📡 Porta {i}:")
        print(f"   Dispositivo: {port.device}")
        print(f"   Descrição: {port.description}")
        print(f"   Fabricante: {port.manufacturer or 'N/A'}")
        
        desc_lower = port.description.lower()
        if any(term in desc_lower for term in 
               ['usb', 'serial', 'uart', 'cp210', 'ch340', 'ft232', 'arduino', 'esp32', 'modem']):
            print(f"   🎯 ADEQUADA para radar")
        else:
            print(f"   ⚠️ Pode não ser adequada")
    
    print("\n" + "=" * 60)
    return [port.device for port in ports]


def main():
    """Função principal do sistema dual radar Gravatá"""
    logger.info("🚀 Inicializando Sistema DUAL RADAR GRAVATÁ...")
    available_ports = list_available_ports()
    if len(available_ports) < 2:
        logger.error("❌ Sistema dual necessita 2 portas seriais!")
        logger.info("💡 Conecte 2 dispositivos radar USB")
        return
    system = GravataDualRadarSystem()
    try:
        if not system.initialize():
            logger.error("❌ Falha na inicialização")
            return
        if not system.start():
            logger.error("❌ Falha ao iniciar sistema")
            return
        
        # Exibe status inicial
        logger.info("=" * 80)
        logger.info("👥 CONTADOR DUAL GRAVATÁ + AUTO-RECUPERAÇÃO v4.3.1")
        logger.info("=" * 80)
        logger.info("🚀 Sistema COMPLETO com Auto-Recovery - Tracking Preciso:")
        logger.info("   • Duas áreas simultâneas (EXTERNA + INTERNA)")
        logger.info("   • Lógica baseada em POSIÇÃO REAL (não IDs do Arduino)")
        logger.info("   • Detecção precisa de entrada/saída por zona")
        logger.info("   • Auto-recuperação Google Sheets com retry")
        logger.info("   • Auto-reconexão serial inteligente")
        logger.info("   • Monitoramento de saúde em background")
        logger.info("   • Restart preventivo após 12 horas")
        logger.info("   • Limpeza de memória automática")
        logger.info("   • Anti-quota inteligente (3min intervalo)")
        logger.info("   • Controle de token expirado")
        logger.info("⚡ RESOLUÇÃO DO PROBLEMA DE 3+ HORAS:")
        logger.info("   • Token expirado ➜ Renovação automática")
        logger.info("   • Quota exceeded ➜ Backoff inteligente")
        logger.info("   • Conexão serial perdida ➜ Reconexão automática")
        logger.info("   • Memória alta ➜ Limpeza automática")
        logger.info("   • Sistema travado ➜ Restart preventivo")
        logger.info("🔄 Sistema HÍBRIDO: Funcionalidades completas + Auto-recovery")
        logger.info("=" * 80)

        # ✅ LOOP PRINCIPAL IGUAL AO SANTA CRUZ
        status_counter = 0
        while True:
            time.sleep(5)  # ✅ IGUAL SANTA CRUZ: sleep(5)
            status_counter += 1
            
            # ✅ IGUAL SANTA CRUZ: Status a cada 30 segundos (6 * 5s = 30s)
            if status_counter >= 6:
                status_counter = 0
                status = system.get_status()
                
                # Status consolidado das duas áreas
                total_current = sum(r['current_count'] for r in status['radars'])
                total_detected = sum(r['total_detected'] for r in status['radars'])
                total_entries = sum(r['entries_count'] for r in status['radars'])
                total_exits = sum(r['exits_count'] for r in status['radars'])
                max_simultaneous = max(r['max_simultaneous'] for r in status['radars'])
                
                logger.info(f"📊 STATUS GRAVATÁ: {total_current} ativas | {total_detected} total | {total_entries} entradas | {total_exits} saídas | Máx: {max_simultaneous}")
                
                # Status individual por área com informações de auto-recuperação
                for radar in status['radars']:
                    area = radar['area_tipo']
                    health = radar.get('health_status', 'unknown')
                    restarts = radar.get('system_restarts', 0)
                    failures = radar.get('consecutive_failures', 0)
                    
                    if radar['running'] and radar['connected'] and health == 'healthy':
                        logger.info(f"   💚 {area}: {radar['current_count']} ativas | {radar['total_detected']} total | Restarts: {restarts}")
                    elif radar['running'] and radar['connected']:
                        logger.warning(f"   💛 {area}: {radar['current_count']} ativas | {radar['total_detected']} total | Problemas: {failures} falhas")
                    elif radar['running']:
                        logger.warning(f"   💛 {area}: rodando mas conexão perdida - tentando auto-recovery...")
                    else:
                        logger.error(f"   ❌ {area}: não está ativo")
                
                # Verifica saúde do Google Sheets para ambas as áreas
                healthy_sheets = 0
                for radar_obj in system.radars:
                    if radar_obj.gsheets_manager and radar_obj.gsheets_manager.health_check():
                        healthy_sheets += 1
                
                if healthy_sheets == len(system.radars):
                    logger.info(f"📊 PLANILHAS: Ambas funcionando normalmente")
                else:
                    logger.warning(f"📊 PLANILHAS: {healthy_sheets}/{len(system.radars)} saudáveis - executando auto-recovery...")
    except KeyboardInterrupt:
        logger.info("🛑 Encerrando por solicitação do usuário...")
    except Exception as e:
        logger.error(f"❌ Erro inesperado: {str(e)}")
        logger.error(traceback.format_exc())
    finally:
        system.stop()
        logger.info("✅ Sistema Dual Radar Gravatá com Auto-Recuperação encerrado!")

if __name__ == "__main__":
    main() 
