#!/usr/bin/env python3
"""
CONTADOR SANTA CRUZ SIMPLIFICADO v1.0
Sistema mais eficaz usando valores diretos do Arduino
Foco na detecção precisa sem complexidade excessiva
"""

import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
import logging
import os
import time
import json
import serial
import threading
import serial.tools.list_ports
import gc
from dotenv import load_dotenv
import subprocess

# Configuração de logging simples
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('santa_cruz_simples.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('santa_cruz_simples')

load_dotenv()

# Configuração do radar
RADAR_CONFIG = {
    'id': 'RADAR_1',
    'name': 'Contador Simplificado',
    'port': '/dev/ttyACM0',
    'baudrate': 115200,
    'spreadsheet_id': '1zVVyL6D9XSrzFvtDxaGJ-3CdniD-gG3Q-bUUXyqr3D4',
    'color': '🟢',
    'description': 'Contador v1.0: Simples e Eficaz'
}

# --- FUNÇÃO PARA RESET DA ESP32 ---
def reset_esp32_via_esptool(serial_port):
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Tentando resetar ESP32 na porta {serial_port} via esptool.py...")
    try:
        command = ['esptool.py', '--port', serial_port, '--before', 'default_reset', 'run']
        result = subprocess.run(command, capture_output=True, text=True, check=True)
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Saída do esptool.py:")
        print(result.stdout)
        if result.stderr:
            print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Erros do esptool.py:")
            print(result.stderr)
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Reset da ESP32 na porta {serial_port} solicitado com sucesso.")
        return True
    except subprocess.CalledProcessError as e:
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] ERRO ao chamar esptool.py: {e}")
        print(f"Stdout: {e.stdout}")
        print(f"Stderr: {e.stderr}")
        return False
    except FileNotFoundError:
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] ERRO: 'esptool.py' não encontrado. Certifique-se de que está no PATH ou o instalou corretamente.")
        return False
    except Exception as e:
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] ERRO inesperado ao resetar ESP32: {e}")
        return False

# --- Porta da ESP32 pode vir do .env ou ser fixa ---
ESP32_SERIAL_PORT = os.getenv("ESP32_SERIAL_PORT", "/dev/ttyACM0")

class SimpleGoogleSheetsManager:
    """Google Sheets Manager Simplificado"""
    
    def __init__(self, creds_path, spreadsheet_id, radar_id):
        SCOPES = [
            'https://www.googleapis.com/auth/spreadsheets',
            'https://www.googleapis.com/auth/drive'
        ]
        self.radar_id = radar_id
        self.spreadsheet_id = spreadsheet_id
        self.last_successful_write = datetime.now()
        
        # Conecta
        self.creds = Credentials.from_service_account_file(creds_path, scopes=SCOPES)
        self.gc = gspread.authorize(self.creds)
        self.spreadsheet = self.gc.open_by_key(self.spreadsheet_id)
        self.worksheet = self.spreadsheet.get_worksheet(0)
        
        self._setup_headers()

    def _setup_headers(self):
        """Configura cabeçalhos simplificados"""
        try:
            headers = self.worksheet.row_values(1)
            expected_headers = [
                'radar_id', 'timestamp', 'person_count', 'distances', 
                'zones', 'avg_confidence', 'total_detected'
            ]
            
            if not headers or len(headers) < 7:
                logger.info("🔧 Configurando cabeçalhos...")
                self.worksheet.clear()
                self.worksheet.append_row(expected_headers)
        except Exception as e:
            logger.warning(f"⚠️ Erro configurando cabeçalhos: {e}")

    def append_row(self, row):
        """Envia linha com retry simples"""
        for attempt in range(2):
            try:
                self.worksheet.append_row(row)
                self.last_successful_write = datetime.now()
                return True
            except Exception as e:
                if attempt == 0:
                    logger.warning(f"⚠️ Erro envio, tentando novamente: {e}")
                    time.sleep(2)
                else:
                    logger.error(f"❌ Falha no envio: {e}")
                    return False
        return False

class SimpleZoneManager:
    """Sistema de zonas simplificado baseado apenas em distância"""
    
    def __init__(self):
        self.ZONES = {
            'MUITO_PERTO': (0.0, 1.0),      # 0-1m - Sala de Reboco
            'PERTO': (1.0, 2.5),            # 1-2.5m - Ativações próximas
            'MEDIO': (2.5, 4.0),            # 2.5-4m - Ativações médias  
            'LONGE': (4.0, 6.0),            # 4-6m - Entrada
            'MUITO_LONGE': (6.0, 10.0)      # 6-10m - Área geral
        }
    
    def get_zone(self, distance):
        """Determina zona pela distância (mais simples e eficaz)"""
        for zone_name, (min_dist, max_dist) in self.ZONES.items():
            if min_dist <= distance < max_dist:
                return zone_name
        return 'FORA_ALCANCE'
    
    def get_zone_description(self, zone_name):
        """Descrição das zonas"""
        descriptions = {
            'MUITO_PERTO': 'Sala Reboco',
            'PERTO': 'Ativações Próximas', 
            'MEDIO': 'Ativações Médias',
            'LONGE': 'Entrada',
            'MUITO_LONGE': 'Área Geral',
            'FORA_ALCANCE': 'Fora de Alcance'
        }
        return descriptions.get(zone_name, zone_name)

class SimpleRadarCounter:
    """Contador Simplificado e Eficaz"""
    
    def __init__(self, config):
        self.config = config
        self.radar_id = config['id']
        self.port = config['port']
        self.baudrate = config['baudrate']
        self.color = config['color']
        
        # Estado simplificado
        self.serial_connection = None
        self.is_running = False
        self.receive_thread = None
        self.gsheets_manager = None
        self.zone_manager = SimpleZoneManager()
        
        # Contadores eficazes
        self.current_people = {}
        self.total_people_detected = 0
        self.max_simultaneous_people = 0
        self.session_start_time = datetime.now()
        
        # Configurações de envio otimizadas
        self.last_sheets_write = 0
        self.sheets_write_interval = 30.0  # 30 segundos (mais responsivo)
        self.pending_data = []
        
        # IDs únicos baseados em posição estável
        self.person_id_counter = 0
        self.last_detection_time = time.time()

    def connect(self):
        """Conecta à porta serial de forma simples"""
        try:
            # Auto-detecta porta se necessário
            if not os.path.exists(self.port):
                detected_port = self.find_serial_port()
                if detected_port:
                    self.port = detected_port
                else:
                    logger.error("❌ Nenhuma porta serial encontrada")
                    return False
            
            logger.info(f"🔌 Conectando à porta {self.port}")
            
            self.serial_connection = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=2.0,
                write_timeout=2.0
            )
            
            time.sleep(3)  # Aguarda estabilização
            
            if self.serial_connection.is_open:
                logger.info(f"✅ Conectado com sucesso!")
                return True
                
        except Exception as e:
            logger.error(f"❌ Erro na conexão: {e}")
            
        return False

    def find_serial_port(self):
        """Detecta porta serial automaticamente"""
        ports = list(serial.tools.list_ports.comports())
        
        for port in ports:
            desc_lower = port.description.lower()
            if any(term in desc_lower for term in
                  ['usb', 'serial', 'arduino', 'esp32', 'cp210', 'ch340']):
                logger.info(f"🔍 Porta detectada: {port.device}")
                return port.device
        
        return None

    def start(self, gsheets_manager):
        """Inicia o radar"""
        self.gsheets_manager = gsheets_manager
        
        if not self.connect():
            return False
        
        self.is_running = True
        self.receive_thread = threading.Thread(target=self.receive_data_loop, daemon=True)
        self.receive_thread.start()
        
        logger.info(f"🚀 Contador simplificado iniciado!")
        return True

    def stop(self):
        """Para o radar"""
        self.is_running = False
        
        if self.serial_connection:
            try:
                self.serial_connection.close()
            except:
                pass
        
        logger.info("🛑 Contador parado!")

    def receive_data_loop(self):
        """Loop de recebimento simplificado com auto recovery e reset ESP32"""
        buffer = ""
        falha_leitura_contador = 0
        
        while self.is_running:
            try:
                if not self.serial_connection or not self.serial_connection.is_open:
                    logger.warning("⚠️ Conexão perdida, tentando reconectar...")
                    if self.connect():
                        buffer = ""
                        falha_leitura_contador = 0
                        continue
                    else:
                        time.sleep(5)
                        continue
                
                # Lê dados disponíveis
                if self.serial_connection.in_waiting > 0:
                    data = self.serial_connection.read(self.serial_connection.in_waiting)
                    text = data.decode('utf-8', errors='ignore')
                    buffer += text
                    falha_leitura_contador = 0  # Resetar contador se dados chegarem
                    
                    # Processa linhas completas
                    if '\n' in buffer:
                        lines = buffer.split('\n')
                        buffer = lines[-1]
                        
                        for line in lines[:-1]:
                            line = line.strip()
                            if line.startswith('{'):
                                try:
                                    data_json = json.loads(line)
                                    self.process_json_data(data_json)
                                except json.JSONDecodeError:
                                    logger.debug(f"JSON inválido: {line[:50]}...")
                else:
                    falha_leitura_contador += 1
                    if falha_leitura_contador >= 100:  # ~10 segundos sem dados (com sleep(0.1))
                        logger.warning(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] NENHUM DADO RECEBIDO DO RADAR POR MUITO TEMPO. TENTANDO RESETAR ESP32...")
                        if reset_esp32_via_esptool(ESP32_SERIAL_PORT):
                            time.sleep(10)  # Dê mais tempo para a ESP32 reiniciar
                            falha_leitura_contador = 0
                            # Tenta reconectar após reset
                            if self.connect():
                                buffer = ""
                                continue
                        else:
                            logger.error(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] FALHA CRÍTICA: Não foi possível resetar a ESP32.")
                            time.sleep(10)
                time.sleep(0.1)
                
            except Exception as e:
                logger.error(f"❌ Erro no loop: {e}")
                time.sleep(2)

    def process_json_data(self, data_json):
        """Processa dados JSON de forma simplificada e eficaz"""
        try:
            radar_id = data_json.get("radar_id", self.radar_id)
            timestamp_ms = data_json.get("timestamp_ms", 0)
            person_count = data_json.get("person_count", 0)
            active_people = data_json.get("active_people", [])
            
            # Timestamp atual
            formatted_timestamp = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
            
            # ✅ TRACKING SIMPLIFICADO MAS EFICAZ
            self.update_people_tracking(active_people)
            
            # ✅ DISPLAY LIMPO E INFORMATIVO
            if os.getenv('TERM'):
                os.system('clear')
            
            print(f"\n{self.color} ═══ CONTADOR SIMPLIFICADO E EFICAZ ═══")
            print(f"⏰ {formatted_timestamp}")
            print(f"📡 {radar_id} | 👥 PESSOAS ATIVAS: {len(active_people)}")
            print(f"🎯 TOTAL DETECTADAS: {self.total_people_detected}")
            print(f"📊 MÁXIMO SIMULTÂNEO: {self.max_simultaneous_people}")
            
            # Runtime
            runtime = datetime.now() - self.session_start_time
            runtime_str = f"{runtime.total_seconds()/60:.1f}min"
            print(f"⏱️ SESSÃO: {runtime_str}")
            
            # Status da planilha
            pending_count = len(self.pending_data)
            if pending_count > 0:
                print(f"📋 BUFFER: {pending_count} linhas | ⏳ Enviando a cada 30s")
            else:
                print(f"📋 PLANILHA: Sincronizada ✅")
            
            if active_people:
                print(f"\n👥 DETECÇÕES ATUAIS ({len(active_people)}):")
                print(f"{'#':<2} {'Distância':<10} {'Zona':<15} {'Confiança':<10}")
                print("-" * 45)
                
                distances = []
                zones = []
                confidences = []
                
                for i, person in enumerate(active_people):
                    # ✅ USA DIRETAMENTE OS VALORES DO ARDUINO (sem cálculos extras)
                    distance = person.get("distance_raw", 0)
                    confidence = person.get("confidence", 85)
                    
                    # ✅ ZONA SIMPLIFICADA BASEADA APENAS EM DISTÂNCIA
                    zone = self.zone_manager.get_zone(distance)
                    zone_desc = self.zone_manager.get_zone_description(zone)
                    
                    print(f"{i+1:<2} {distance:<10.2f} {zone_desc:<15} {confidence:<10}%")
                    
                    distances.append(distance)
                    zones.append(zone)
                    confidences.append(confidence)
                
                # ✅ PREPARA DADOS PARA PLANILHA (simplificado)
                if self.gsheets_manager:
                    avg_distance = sum(distances) / len(distances)
                    avg_confidence = sum(confidences) / len(confidences)
                    zones_str = ",".join(sorted(set(zones)))
                    distances_str = ",".join([f"{d:.1f}" for d in distances])
                    
                    row = [
                        radar_id,                           # radar_id
                        formatted_timestamp,                # timestamp  
                        len(active_people),                 # person_count
                        distances_str,                      # distances (todas)
                        zones_str,                          # zones (únicas)
                        f"{avg_confidence:.0f}",            # avg_confidence
                        self.total_people_detected          # total_detected
                    ]
                    
                    self.pending_data.append(row)
                    logger.info(f"📋 Dados adicionados: {len(active_people)} pessoas detectadas")
                
                print(f"\n📊 RESUMO:")
                print(f"   • Distância média: {sum(distances)/len(distances):.1f}m")
                print(f"   • Confiança média: {sum(confidences)/len(confidences):.0f}%")
                print(f"   • Zonas ativas: {', '.join(set(self.zone_manager.get_zone_description(z) for z in zones))}")
                
            else:
                print(f"\n👻 Nenhuma pessoa detectada no momento")
                
                # Envia dados zerados se mudou de estado
                if self.gsheets_manager and hasattr(self, 'last_person_count'):
                    if getattr(self, 'last_person_count', 0) > 0:
                        row = [
                            radar_id, formatted_timestamp, 0, "0", "VAZIA", "0", self.total_people_detected
                        ]
                        self.pending_data.append(row)
                        logger.info(f"📋 Área vazia detectada")
            
            # Armazena último count para detectar mudanças
            setattr(self, 'last_person_count', len(active_people))
            
            print("\n" + "=" * 50)
            print("🎯 SISTEMA SIMPLIFICADO E EFICAZ")
            print("✅ Usa valores diretos do Arduino")  
            print("✅ Zonas baseadas em distância")
            print("✅ Tracking preciso e simples")
            print("✅ Envio otimizado (30s intervalo)")
            print("⚡ Pressione Ctrl+C para encerrar")
            
            # ✅ ENVIA DADOS PARA PLANILHA
            self.send_pending_data()
            
        except Exception as e:
            logger.error(f"❌ Erro processando JSON: {e}")

    def update_people_tracking(self, active_people):
        """Sistema de tracking simplificado mas preciso"""
        current_time = time.time()
        
        # ✅ LÓGICA SIMPLIFICADA: conta pessoas novas por distância única
        current_distances = set()
        
        for person in active_people:
            distance = person.get("distance_raw", 0)
            # Agrupa por distância (arredondada para evitar micro-variações)
            rounded_distance = round(distance, 1)
            current_distances.add(rounded_distance)
        
        # ✅ DETECTA NOVAS PESSOAS (distâncias que não existiam antes)
        previous_distances = getattr(self, 'last_distances', set())
        new_distances = current_distances - previous_distances
        
        if new_distances:
            new_count = len(new_distances)
            self.total_people_detected += new_count
            logger.info(f"🆕 {new_count} nova(s) pessoa(s) detectada(s)!")
        
        # ✅ ATUALIZA MÁXIMO SIMULTÂNEO
        current_count = len(active_people)
        if current_count > self.max_simultaneous_people:
            self.max_simultaneous_people = current_count
            logger.info(f"📊 Novo máximo simultâneo: {current_count} pessoas")
        
        # Armazena para próxima comparação
        setattr(self, 'last_distances', current_distances)
        self.last_detection_time = current_time

    def send_pending_data(self):
        """Envia dados para planilha de forma otimizada"""
        try:
            current_time = time.time()
            
            # Verifica intervalo
            if (current_time - self.last_sheets_write) < self.sheets_write_interval:
                return
            
            if not self.pending_data or not self.gsheets_manager:
                return
            
            # Envia todas as linhas pendentes
            if self.pending_data:
                logger.info(f"📊 Enviando {len(self.pending_data)} linhas...")
                
                for row in self.pending_data:
                    success = self.gsheets_manager.append_row(row)
                    if not success:
                        logger.warning("⚠️ Falha no envio, tentando na próxima")
                        return
                    time.sleep(0.3)  # Pausa entre linhas
                
                logger.info(f"✅ {len(self.pending_data)} linhas enviadas!")
                self.last_sheets_write = current_time
                self.pending_data = []  # Limpa buffer
                
        except Exception as e:
            logger.error(f"❌ Erro no envio: {e}")

    def get_status(self):
        """Status simplificado"""
        return {
            'id': self.radar_id,
            'running': self.is_running,
            'connected': bool(self.serial_connection and self.serial_connection.is_open),
            'total_detected': self.total_people_detected,
            'max_simultaneous': self.max_simultaneous_people,
            'session_duration': (datetime.now() - self.session_start_time).total_seconds()
        }

def main():
    """Função principal simplificada"""
    logger.info("🚀 Iniciando Contador Simplificado...")
    
    # Google Sheets
    script_dir = os.path.dirname(os.path.abspath(__file__))
    credentials_file = os.path.join(script_dir, 'serial_radar', 'credenciais.json')
    
    if not os.path.exists(credentials_file):
        logger.error(f"❌ Credenciais não encontradas: {credentials_file}")
        return
    
    try:
        gsheets_manager = SimpleGoogleSheetsManager(
            credentials_file, 
            RADAR_CONFIG['spreadsheet_id'],
            RADAR_CONFIG['id']
        )
        logger.info("✅ Google Sheets configurado")
    except Exception as e:
        logger.error(f"❌ Erro configurando Sheets: {e}")
        return
    
    # Radar
    radar = SimpleRadarCounter(RADAR_CONFIG)
    
    try:
        if not radar.start(gsheets_manager):
            logger.error("❌ Falha ao iniciar radar")
            return
        
        logger.info("=" * 60)
        logger.info("🟢 CONTADOR SANTA CRUZ SIMPLIFICADO v1.0")
        logger.info("=" * 60)
        logger.info("🎯 CARACTERÍSTICAS:")
        logger.info("   ✅ Usa valores diretos do Arduino (distance_raw)")
        logger.info("   ✅ Zonas baseadas apenas em distância")
        logger.info("   ✅ Tracking simplificado mas preciso") 
        logger.info("   ✅ Menos complexidade, mais eficácia")
        logger.info("   ✅ Envio otimizado a cada 30 segundos")
        logger.info("   ✅ Auto-detecção de porta serial")
        logger.info("   ✅ Display limpo e informativo")
        logger.info("🚀 OTIMIZAÇÕES:")
        logger.info("   • Arduino já calcula distâncias")
        logger.info("   • Sem cálculos redundantes")
        logger.info("   • Zonas por faixas de distância")
        logger.info("   • Tracking por distância única")
        logger.info("   • Buffer inteligente para planilha")
        logger.info("=" * 60)
        
        # Loop principal simples
        while True:
            time.sleep(10)
            status = radar.get_status()
            
            if status['running'] and status['connected']:
                logger.debug(f"💚 Sistema funcionando: {status['total_detected']} total detectadas")
            else:
                logger.warning(f"💛 Problemas na conexão - tentando reconectar...")
    
    except KeyboardInterrupt:
        logger.info("🛑 Encerrando por solicitação do usuário...")
    
    except Exception as e:
        logger.error(f"❌ Erro inesperado: {e}")
    
    finally:
        radar.stop()
        logger.info("✅ Sistema encerrado!")

if __name__ == "__main__":
    main() 
