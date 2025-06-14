import subprocess
import time
import os

def reset_esp32_via_esptool(serial_port):
    print(f"Tentando resetar ESP32 na porta {serial_port} via esptool.py...")
    try:
        command = ['esptool.py', '--port', serial_port, '--before', 'default_reset', 'run']
        result = subprocess.run(command, capture_output=True, text=True, check=True)
        print("Saída do esptool.py:")
        print(result.stdout)
        if result.stderr:
            print("Erros do esptool.py:")
            print(result.stderr)
        print(f"Reset da ESP32 na porta {serial_port} solicitado com sucesso.")
        return True
    except subprocess.CalledProcessError as e:
        print(f"ERRO ao chamar esptool.py: {e}")
        print(f"Stdout: {e.stdout}")
        print(f"Stderr: {e.stderr}")
        return False
    except FileNotFoundError:
        print("ERRO: 'esptool.py' não encontrado. Certifique-se de que está no PATH ou o instalou corretamente.")
        return False
    except Exception as e:
        print(f"ERRO inesperado ao resetar ESP32: {e}")
        return False

if __name__ == "__main__":
    # Defina a porta serial da sua ESP32
    ESP32_SERIAL_PORT = os.getenv("ESP32_SERIAL_PORT", "/dev/ttyACM0")
    if reset_esp32_via_esptool(ESP32_SERIAL_PORT):
        print("ESP32 resetada com sucesso! Aguardando alguns segundos para reinicialização...")
        time.sleep(5)
    else:
        print("Falha ao resetar a ESP32.")
