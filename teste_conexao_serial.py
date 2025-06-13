#!/usr/bin/env python3
"""
RESET RADAR GRAVATA v1.0
Sistema para reset automático da ESP32 ao iniciar
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
        self.use_direct_reset = True  # Usar reset direto via DTR/RTS

    def direct_reset_esp32(self):
        """Reseta a ESP32 diretamente via DTR/RTS"""
        logger.info(f"🔄 Tentando resetar ESP32 na porta {self.port} diretamente (DTR/RTS)...")
        try:
            ser = serial.Serial(self.port, self.baudrate, timeout=1)
            ser.dtr = 0
            ser.rts = 0
            time.sleep(0.1)
            ser.dtr = 1
            ser.rts = 1
            time.sleep(0.1)
            ser.close()
            logger.info(f"✅ Reset da ESP32 na porta {self.port} solicitado com sucesso (direto).")
            return True
        except serial.SerialException as e:
            logger.error(f"Erro na porta serial: {e}")
            logger.error("Verifique se a porta está correta, se o dispositivo está conectado e as permissões.")
            return False
        except Exception as e:
            logger.error(f"Ocorreu um erro inesperado: {e}")
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

    def reset_and_connect(self):
        """Realiza o reset e conecta ao radar"""
        try:
            # Garante que a porta está definida
            if not self.port:
                self.port = self.find_serial_port()
                if not self.port:
                    logger.error("❌ Nenhuma porta serial encontrada para reset!")
                    return False

            # Tenta reset direto se habilitado
            if self.use_direct_reset:
                if self.direct_reset_esp32():
                    logger.info("⏳ Aguardando 5 segundos para ESP32 reiniciar...")
                    time.sleep(5)  # Aguarda reinicialização completa
                else:
                    logger.warning("⚠️ Reset direto falhou, tentando conexão normal...")
            
            # Tenta conectar
            if self.connect():
                logger.info(f"✅ Conexão estabelecida com sucesso!")
                return True
            else:
                logger.error("❌ Falha ao estabelecer conexão")
                return False
                
        except Exception as e:
            logger.error(f"❌ Erro durante reset e conexão: {e}")
            return False

    def close(self):
        """Fecha a conexão serial"""
        if self.serial_connection and self.serial_connection.is_open:
            self.serial_connection.close()
            logger.info("🔌 Conexão serial fechada")

def main():
    """Função principal para reset do radar"""
    logger.info("🚀 Iniciando Sistema de Reset do Radar...")
    
    # Cria instância do reset
    radar = RadarReset()
    
    try:
        logger.info("=" * 60)
        logger.info("🔵 SISTEMA DE RESET DO RADAR v1.0")
        logger.info("=" * 60)
        logger.info("🎯 CARACTERÍSTICAS:")
        logger.info("   ✅ Reset automático ao iniciar")
        logger.info("   ✅ Reset direto via DTR/RTS (sem esptool.py)")
        logger.info("   ✅ Auto-detecção de porta serial")
        logger.info("=" * 60)
        
        # Realiza reset e conexão
        if radar.reset_and_connect():
            logger.info("✅ Radar resetado e conectado com sucesso!")
        else:
            logger.error("❌ Falha ao resetar e conectar ao radar")
        
    except KeyboardInterrupt:
        logger.info("🛑 Encerrando por solicitação do usuário...")
    
    except Exception as e:
        logger.error(f"❌ Erro inesperado: {e}")
    
    finally:
        radar.close()
        logger.info("✅ Sistema encerrado!")

if __name__ == "__main__":
    main() 
