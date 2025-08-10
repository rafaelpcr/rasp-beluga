#!/usr/bin/env python3
"""
Script para configurar credenciais na Raspberry Pi
Autor: Sistema Beluga
Data: 2024
"""

import os
import shutil
import json
from pathlib import Path

def setup_raspberry_credentials():
    """
    Configura as credenciais para uso na Raspberry Pi
    """
    print("🔐 CONFIGURADOR DE CREDENCIAIS PARA RASPBERRY PI")
    print("=" * 50)
    
    # Diretórios possíveis para credenciais
    possible_paths = [
        "/home/beluga/rasp-beluga/credenciais.json",
        "/home/pi/belugateste/serial_radar/credenciais.json",
        "/home/pi/credenciais.json",
        "./credenciais.json",
        "serial_radar/credenciais.json"
    ]
    
    # Encontrar arquivo de credenciais
    credentials_file = None
    for path in possible_paths:
        if os.path.exists(path):
            credentials_file = path
            print(f"✅ Encontrado arquivo de credenciais em: {path}")
            break
    
    if not credentials_file:
        print("❌ Arquivo de credenciais não encontrado!")
        print("\n📁 Locais onde procurar:")
        for path in possible_paths:
            print(f"   - {path}")
        print("\n💡 Copie o arquivo 'credenciais.json' para um desses locais")
        return False
    
    # Verificar se as credenciais são válidas
    try:
        with open(credentials_file, 'r') as f:
            creds = json.load(f)
        
        required_fields = ['type', 'project_id', 'private_key', 'client_email']
        missing_fields = [field for field in required_fields if field not in creds]
        
        if missing_fields:
            print(f"❌ Credenciais inválidas! Campos faltando: {missing_fields}")
            return False
        
        print(f"✅ Credenciais válidas para projeto: {creds.get('project_id', 'N/A')}")
        print(f"✅ Email da conta de serviço: {creds.get('client_email', 'N/A')}")
        
    except Exception as e:
        print(f"❌ Erro ao ler credenciais: {e}")
        return False
    
    # Configurar para uso no sistema
    target_dir = "serial_radar"
    target_file = os.path.join(target_dir, "credenciais.json")
    
    # Criar diretório se não existir
    os.makedirs(target_dir, exist_ok=True)
    
    # Copiar credenciais para o local padrão
    try:
        shutil.copy2(credentials_file, target_file)
        print(f"✅ Credenciais copiadas para: {target_file}")
    except Exception as e:
        print(f"❌ Erro ao copiar credenciais: {e}")
        return False
    
    # Testar conexão
    print("\n🧪 Testando conexão com Google Sheets...")
    try:
        from google.oauth2.service_account import Credentials
        from googleapiclient.discovery import build
        
        SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
        creds = Credentials.from_service_account_file(target_file, scopes=SCOPES)
        service = build('sheets', 'v4', credentials=creds)
        
        print("✅ Conexão com Google Sheets estabelecida com sucesso!")
        return True
        
    except ImportError:
        print("⚠️  Bibliotecas Google não instaladas. Execute:")
        print("   pip install google-auth google-auth-oauthlib google-auth-httplib2 google-api-python-client")
        return False
    except Exception as e:
        print(f"❌ Erro ao testar conexão: {e}")
        return False

def create_env_file():
    """
    Cria arquivo .env com configurações
    """
    env_content = """# Configurações do Sistema Beluga
# Credenciais Google Sheets
GOOGLE_CREDENTIALS=serial_radar/credenciais.json

# Configurações do banco de dados
DB_HOST=localhost
DB_USER=root
DB_PASSWORD=
DB_NAME=radar_serial
DB_PORT=3306

# Configurações da porta serial
SERIAL_PORT=/dev/ttyUSB0
SERIAL_BAUDRATE=115200

# Configurações do sistema
LOG_LEVEL=INFO
AUTO_RECOVERY=true
"""
    
    with open('.env', 'w') as f:
        f.write(env_content)
    
    print("✅ Arquivo .env criado com configurações padrão")

def main():
    """
    Função principal
    """
    print("🚀 Iniciando configuração do sistema...")
    
    # Configurar credenciais
    if setup_raspberry_credentials():
        print("\n✅ Configuração de credenciais concluída!")
        
        # Criar arquivo .env
        create_env_file()
        
        print("\n📋 PRÓXIMOS PASSOS:")
        print("1. Execute: python3 test_credentials.py")
        print("2. Execute: python3 test_gsheets_connection.py")
        print("3. Configure o banco de dados se necessário")
        print("4. Teste o sistema: python3 radar_serial_gsheets.py")
        
    else:
        print("\n❌ Configuração falhou!")
        print("Verifique se o arquivo de credenciais está correto")

if __name__ == "__main__":
    main()
