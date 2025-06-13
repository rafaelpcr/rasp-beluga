#!/usr/bin/env python3
"""
RESET RADAR GRAVATA v1.0
Sistema isolado para reinicialização de conexão serial dos radares
Usa esptool.py para reset hardware da ESP32
"""

import serial
import serial.tools.list_ports
import time
import logging
import os
import subprocess
from datetime import datetime

# Configuração de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('reset_radar.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('reset_radar')

class RadarReset:
    def __init__(self, port=None, baudrate=115200):
        self.port = port
        self.baudrate = baudrate
        self.serial_connection = None
        self.last_data_time = time.time()
        self.data_timeout = 60.0  # 60 segundos (1 minuto) sem dados = reiniciar
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 3
        self.reconnect_delay = 5.0  # 5 segundos entre tentativas
        self.is_running = False
        self.use_esptool = True  # Usar esptool.py para reset hardware

    def reset_esp32_via_esptool(self):
        """Reseta a ESP32 usando esptool.py (reset hardware)"""
        logger.info(f"🔄 Tentando reset hardware da ESP32 na porta {self.port} via esptool.py...")
        try:
            # Comando para resetar a ESP32
            command = ['esptool.py', '--port', self.port, '--before', 'default_reset', 'run']
            
            # Executa o comando e captura a saída
            result = subprocess.run(command, capture_output=True, text=True, check=True)
            
            logger.info("📝 Saída do esptool.py:")
            logger.info(result.stdout)
            if result.stderr:
                logger.warning("⚠️ Erros do esptool.py:")
                logger.warning(result.stderr)
            
            logger.info(f"✅ Reset hardware da ESP32 na porta {self.port} realizado com sucesso!")
            return True
            
        except subprocess.CalledProcessError as e:
            logger.error(f"❌ Erro ao chamar esptool.py: {e}")
            logger.error(f"📝 Stdout: {e.stdout}")
            logger.error(f"❌ Stderr: {e.stderr}")
            return False
            
        except FileNotFoundError:
            logger.error("❌ Erro: 'esptool.py' não encontrado. Instalando...")
            try:
                # Tenta instalar o esptool.py
                subprocess.run(['pip', 'install', 'esptool'], check=True)
                logger.info("✅ esptool.py instalado com sucesso!")
                # Tenta novamente após instalação
                return self.reset_esp32_via_esptool()
            except Exception as install_error:
                logger.error(f"❌ Falha ao instalar esptool.py: {install_error}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Erro inesperado no reset hardware: {e}")
            return False

    def find_serial_port(self):
        """Detecta porta serial automaticamente"""
        ports = list(serial.tools.list_ports.comports())
        
        for port in ports:
            desc_lower = port.description.lower()
            # Inclui usbmodem para macOS
            if (any(term in desc_lower for term in
                  ['usb', 'serial', 'arduino', 'esp32', 'cp210', 'ch340']) or 
                'usbmodem' in port.device):
                logger.info(f"🔍 Porta detectada: {port.device}")
                return port.device
        
        return None

    def connect(self):
        """Conecta à porta serial"""
        try:
            # Se porta não especificada, tenta detectar
            if not self.port:
                self.port = self.find_serial_port()
                if not self.port:
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

    def reset_connection(self):
        """Reinicia a conexão serial completamente"""
        logger.warning(f"🔄 Tentando reiniciar conexão serial...")
        
        try:
            # Fecha conexão atual se existir
            if self.serial_connection and self.serial_connection.is_open:
                self.serial_connection.close()
                time.sleep(1)
            
            # Tenta reset hardware se esptool estiver habilitado
            if self.use_esptool:
                if self.reset_esp32_via_esptool():
                    logger.info("⏳ Aguardando 5 segundos para ESP32 reiniciar...")
                    time.sleep(5)  # Aguarda reinicialização completa
                else:
                    logger.warning("⚠️ Reset hardware falhou, tentando reconexão normal...")
            
            # Tenta reconectar
            if self.connect():
                self.reconnect_attempts = 0
                logger.info(f"✅ Conexão serial reiniciada com sucesso!")
                return True
            else:
                self.reconnect_attempts += 1
                logger.error(f"❌ Falha ao reiniciar conexão (tentativa {self.reconnect_attempts}/{self.max_reconnect_attempts})")
                return False
                
        except Exception as e:
            logger.error(f"❌ Erro ao reiniciar conexão: {e}")
            return False

    def monitor_connection(self):
        """Monitora a conexão e reinicia se necessário"""
        self.is_running = True
        buffer = ""
        
        while self.is_running:
            try:
                if not self.serial_connection or not self.serial_connection.is_open:
                    logger.warning("⚠️ Conexão perdida, tentando reconectar...")
                    if self.connect():
                        buffer = ""
                        continue
                    else:
                        time.sleep(5)
                        continue

                # Lê dados disponíveis
                if self.serial_connection.in_waiting > 0:
                    data = self.serial_connection.read(self.serial_connection.in_waiting)
                    text = data.decode('utf-8', errors='ignore')
                    buffer += text
                    
                    # Atualiza timestamp do último dado recebido
                    self.last_data_time = time.time()
                    
                    # Processa linhas completas
                    if '\n' in buffer:
                        lines = buffer.split('\n')
                        buffer = lines[-1]
                        
                        for line in lines[:-1]:
                            line = line.strip()
                            if line:
                                logger.info(f"📡 Dados recebidos: {line[:50]}...")

                # Verifica timeout de dados
                current_time = time.time()
                if (current_time - self.last_data_time) > self.data_timeout:
                    logger.warning(f"⚠️ Timeout de dados detectado ({self.data_timeout}s sem receber dados)")
                    
                    if self.reconnect_attempts < self.max_reconnect_attempts:
                        if self.reset_connection():
                            self.last_data_time = current_time
                            continue
                        else:
                            time.sleep(self.reconnect_delay)
                    else:
                        logger.error("❌ Máximo de tentativas de reconexão atingido!")
                        self.is_running = False
                        break

                time.sleep(0.1)

            except Exception as e:
                logger.error(f"❌ Erro no monitoramento: {e}")
                time.sleep(2)

    def stop(self):
        """Para o monitoramento"""
        self.is_running = False
        if self.serial_connection and self.serial_connection.is_open:
            self.serial_connection.close()
        logger.info("🛑 Monitoramento encerrado!")

def main():
    """Função principal para testar o reset do radar"""
    logger.info("🚀 Iniciando Sistema de Reset do Radar...")
    
    # Cria instância do reset
    radar = RadarReset()
    
    try:
        # Tenta conectar
        if not radar.connect():
            logger.error("❌ Não foi possível conectar ao radar")
            return
        
        logger.info("=" * 60)
        logger.info("🔵 SISTEMA DE RESET DO RADAR v1.0")
        logger.info("=" * 60)
        logger.info("🎯 CARACTERÍSTICAS:")
        logger.info("   ✅ Monitoramento contínuo da conexão")
        logger.info("   ✅ Reset hardware via esptool.py")
        logger.info("   ✅ Reinicialização automática em caso de timeout")
        logger.info("   ✅ Máximo de 3 tentativas de reconexão")
        logger.info("   ✅ Timeout de 60 segundos sem dados")
        logger.info("   ✅ Delay de 5 segundos entre tentativas")
        logger.info("=" * 60)
        
        # Inicia monitoramento
        radar.monitor_connection()
        
    except KeyboardInterrupt:
        logger.info("🛑 Encerrando por solicitação do usuário...")
    
    except Exception as e:
        logger.error(f"❌ Erro inesperado: {e}")
    
    finally:
        radar.stop()
        logger.info("✅ Sistema encerrado!")

if __name__ == "__main__":
    main() 
