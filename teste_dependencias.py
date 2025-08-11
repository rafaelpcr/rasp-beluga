#!/usr/bin/env python3
"""
Script para testar dependências do Sistema Dual de Radares
"""

import sys
import os

def test_imports():
    """Testa se todas as dependências podem ser importadas"""
    print("🧪 Testando dependências do Sistema Dual de Radares...")
    print("=" * 50)
    
    tests = [
        ("serial", "pyserial"),
        ("gspread", "gspread"),
        ("google.oauth2.service_account", "google-auth"),
        ("dotenv", "python-dotenv"),
        ("numpy", "numpy"),
    ]
    
    failed_imports = []
    
    for module, package in tests:
        try:
            __import__(module)
            print(f"✅ {module} - OK")
        except ImportError as e:
            print(f"❌ {module} - FALHOU")
            print(f"   Erro: {e}")
            print(f"   Instale com: pip install {package}")
            failed_imports.append(package)
    
    # Teste específico para serial.tools
    try:
        import serial.tools.list_ports
        print("✅ serial.tools.list_ports - OK")
    except ImportError:
        print("❌ serial.tools.list_ports - FALHOU")
        print("   Instale com: pip install pyserial")
        failed_imports.append("pyserial")
    
    print("\n" + "=" * 50)
    
    if failed_imports:
        print(f"❌ {len(failed_imports)} dependência(s) falharam:")
        for package in failed_imports:
            print(f"   - {package}")
        print("\n💡 Execute o script de instalação:")
        print("   ./install_raspberry_dependencies.sh")
        return False
    else:
        print("🎉 Todas as dependências estão funcionando!")
        return True

def test_serial_ports():
    """Testa detecção de portas seriais"""
    print("\n🔍 Testando detecção de portas seriais...")
    
    try:
        import serial.tools.list_ports
        
        ports = list(serial.tools.list_ports.comports())
        print(f"📋 {len(ports)} porta(s) encontrada(s):")
        
        for i, port in enumerate(ports):
            print(f"   {i+1}. {port.device}")
            print(f"      Descrição: {port.description}")
        
        return True
        
    except ImportError:
        print("⚠️ serial.tools.list_ports não disponível")
        print("   Tentando detecção manual...")
        
        try:
            import glob
            import os
            
            port_patterns = ['/dev/ttyUSB*', '/dev/ttyACM*', '/dev/ttyS*', '/dev/ttyAMA*']
            all_ports = []
            
            for pattern in port_patterns:
                ports = glob.glob(pattern)
                all_ports.extend(ports)
            
            if all_ports:
                print(f"📋 {len(all_ports)} porta(s) encontrada(s) manualmente:")
                for port in all_ports:
                    print(f"   - {port}")
                return True
            else:
                print("❌ Nenhuma porta serial encontrada")
                return False
                
        except Exception as e:
            print(f"❌ Erro na detecção manual: {e}")
            return False

def test_google_sheets():
    """Testa conexão com Google Sheets"""
    print("\n📊 Testando conexão com Google Sheets...")
    
    # Verifica arquivo de credenciais
    creds_file = 'credenciais2.json'
    if not os.path.exists(creds_file):
        print(f"❌ Arquivo de credenciais não encontrado: {creds_file}")
        return False
    
    print(f"✅ Arquivo de credenciais encontrado: {creds_file}")
    
    try:
        import gspread
        from google.oauth2.service_account import Credentials
        
        SCOPES = [
            'https://www.googleapis.com/auth/spreadsheets',
            'https://www.googleapis.com/auth/drive.readonly'
        ]
        
        creds = Credentials.from_service_account_file(creds_file, scopes=SCOPES)
        gc = gspread.authorize(creds)
        
        print("✅ Autenticação com Google Sheets OK")
        
        # Testa acesso às planilhas configuradas
        test_spreadsheets = ['Projeto_cocacola_radar1', 'Projeto_cocacola_radar2']
        
        for name in test_spreadsheets:
            try:
                spreadsheet = gc.open(name)
                print(f"✅ Acesso à planilha '{name}' OK")
            except Exception as e:
                print(f"❌ Erro ao acessar '{name}': {type(e).__name__}")
        
        return True
        
    except Exception as e:
        print(f"❌ Erro na conexão com Google Sheets: {type(e).__name__} - {e}")
        return False

def main():
    """Função principal"""
    print("🚀 TESTE DE DEPENDÊNCIAS - SISTEMA DUAL DE RADARES")
    print("=" * 60)
    
    # Testa imports
    imports_ok = test_imports()
    
    if not imports_ok:
        print("\n❌ Dependências básicas falharam. Instale-as primeiro.")
        sys.exit(1)
    
    # Testa portas seriais
    serial_ok = test_serial_ports()
    
    # Testa Google Sheets
    gsheets_ok = test_google_sheets()
    
    # Resumo final
    print("\n" + "=" * 60)
    print("📋 RESUMO DOS TESTES")
    print("=" * 60)
    
    print(f"✅ Imports: {'OK' if imports_ok else 'FALHOU'}")
    print(f"✅ Portas Seriais: {'OK' if serial_ok else 'FALHOU'}")
    print(f"✅ Google Sheets: {'OK' if gsheets_ok else 'FALHOU'}")
    
    if imports_ok and serial_ok and gsheets_ok:
        print("\n🎉 Todos os testes passaram! Sistema pronto para uso.")
        print("\n📝 Para executar:")
        print("   python3 radar_serial_gsheets.py")
    else:
        print("\n⚠️ Alguns testes falharam. Verifique os erros acima.")
        
        if not serial_ok:
            print("\n💡 Para problemas de portas seriais:")
            print("   ./install_raspberry_dependencies.sh")
        
        if not gsheets_ok:
            print("\n💡 Para problemas do Google Sheets:")
            print("   Verifique o arquivo credenciais2.json")
    
    return imports_ok and serial_ok and gsheets_ok

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
