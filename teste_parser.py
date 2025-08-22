#!/usr/bin/env python3
"""
Teste completo do parser do radar para identificar por que dados estão chegando em 0
Baseado no código radar_usb_otimizado.ino
"""

import re
import math
import json

def parse_serial_data(raw_data):
    """
    Parser atualizado para o formato do radar_usb_otimizado.ino
    """
    try:
        print(f"🔍 [PARSER] Processando dados: {raw_data[:200]}...")
        
        # FORMATO 1: Formato atual do radar (Human Detected + Target)
        # -----Human Detected-----
        # breath_rate: 30.00
        # heart_rate: 82.00
        # x_position: -0.15
        # y_position: 0.38
        # distance: -0.00
        # Target 1:
        #   x_point: -0.15
        #   y_point: 0.38
        #   dop_index: 0
        #   cluster_index: 0
        #   move_speed: 0.00 cm/s
        
        has_human_detected = '-----Human Detected-----' in raw_data
        has_target_1 = 'Target 1:' in raw_data
        
        if has_human_detected:
            print("✅ [PARSER] Formato 'Human Detected' detectado")
            
            # Extrai dados básicos
            breath_match = re.search(r'breath_rate:\s*([-\d.]+)', raw_data)
            heart_match = re.search(r'heart_rate:\s*([-\d.]+)', raw_data)
            x_pos_match = re.search(r'x_position:\s*([-\d.]+)', raw_data)
            y_pos_match = re.search(r'y_position:\s*([-\d.]+)', raw_data)
            distance_match = re.search(r'distance:\s*([-\d.]+)', raw_data)
            
            # Extrai dados do Target se disponível
            x_point_match = re.search(r'x_point:\s*([-\d.]+)', raw_data)
            y_point_match = re.search(r'y_point:\s*([-\d.]+)', raw_data)
            move_speed_match = re.search(r'move_speed:\s*([-\d.]+)\s*cm/s', raw_data)
            
            # Constrói o dicionário de dados
            data = {}
            
            # Dados básicos
            data['breath_rate'] = float(breath_match.group(1)) if breath_match else 0.0
            data['heart_rate'] = float(heart_match.group(1)) if heart_match else 0.0
            data['distance'] = float(distance_match.group(1)) if distance_match else 0.0
            
            # Posição X,Y (prioriza x_point/y_point se disponível)
            if x_point_match and y_point_match:
                data['x_point'] = float(x_point_match.group(1))
                data['y_point'] = float(y_point_match.group(1))
                print(f"📍 [PARSER] Usando x_point/y_point: X={data['x_point']}, Y={data['y_point']}")
            elif x_pos_match and y_pos_match:
                data['x_point'] = float(x_pos_match.group(1))
                data['y_point'] = float(y_pos_match.group(1))
                print(f"📍 [PARSER] Usando x_position/y_position: X={data['x_point']}, Y={data['y_point']}")
            else:
                data['x_point'] = 0.0
                data['y_point'] = 0.0
                print("⚠️ [PARSER] Nenhuma posição X,Y encontrada!")
            
            # Velocidade (converte de cm/s para m/s)
            if move_speed_match:
                speed_cm_s = float(move_speed_match.group(1))
                data['move_speed'] = speed_cm_s / 100.0  # Converte para m/s
                print(f"🏃 [PARSER] Velocidade: {speed_cm_s} cm/s = {data['move_speed']} m/s")
            else:
                data['move_speed'] = 0.0
                print("⚠️ [PARSER] Velocidade não encontrada!")
            
            # Adiciona campos padrão
            data['timestamp'] = 0
            data['radar_id'] = 'RADAR_1'
            data['is_simulated'] = False
            
            print(f"✅ [PARSER] Dados parseados com sucesso:")
            print(f"   X: {data['x_point']}m")
            print(f"   Y: {data['y_point']}m")
            print(f"   ❤️: {data['heart_rate']} BPM")
            print(f"   🫁: {data['breath_rate']} resp/min")
            print(f"   🏃: {data['move_speed']} m/s")
            print(f"   📏: {data['distance']}m")
            
            return data
            
        else:
            print("❌ [PARSER] Formato 'Human Detected' não detectado")
            return None
            
    except Exception as e:
        print(f"❌ [PARSER] Erro ao processar dados: {e}")
        return None

def test_parser():
    print("🧪 TESTE COMPLETO DO PARSER DO RADAR")
    print("=" * 60)
    
    # Teste 1: Dados reais do radar (formato esperado)
    print("\n📡 TESTE 1: Dados reais do radar (formato esperado)")
    print("-" * 50)
    
    radar_data = """-----Human Detected-----
breath_rate: 30.00
heart_rate: 82.00
x_position: -0.15
y_position: 0.38
distance: 1.25
Target 1:
  x_point: -0.15
  y_point: 0.38
  dop_index: 0
  cluster_index: 0
  move_speed: 15.50 cm/s"""
    
    result = parse_serial_data(radar_data)
    
    if result:
        print("\n✅ TESTE 1 PASSOU!")
        print(f"   X: {result.get('x_point', 0)}m")
        print(f"   Y: {result.get('y_point', 0)}m")
        print(f"   ❤️: {result.get('heart_rate', 0)} BPM")
        print(f"   🫁: {result.get('breath_rate', 0)} resp/min")
        print(f"   🏃: {result.get('move_speed', 0)} m/s")
        print(f"   📏: {result.get('distance', 0)}m")
    else:
        print("\n❌ TESTE 1 FALHOU!")
    
    # Teste 2: Dados com valores 0 (problema atual)
    print("\n📡 TESTE 2: Dados com valores 0 (problema atual)")
    print("-" * 50)
    
    radar_data_zero = """-----Human Detected-----
breath_rate: 0.00
heart_rate: 0.00
x_position: 0.00
y_position: 0.00
distance: 0.00
Target 1:
  x_point: 0.00
  y_point: 0.00
  dop_index: 0
  cluster_index: 0
  move_speed: 0.00 cm/s"""
    
    result_zero = parse_serial_data(radar_data_zero)
    
    if result_zero:
        print("\n✅ TESTE 2 PASSOU!")
        print(f"   X: {result_zero.get('x_point', 0)}m")
        print(f"   Y: {result_zero.get('y_point', 0)}m")
        print(f"   ❤️: {result_zero.get('heart_rate', 0)} BPM")
        print(f"   🫁: {result_zero.get('breath_rate', 0)} resp/min")
        print(f"   🏃: {result_zero.get('move_speed', 0)} m/s")
        print(f"   📏: {result_zero.get('distance', 0)}m")
    else:
        print("\n❌ TESTE 2 FALHOU!")
    
    # Teste 3: Dados parciais (sem Target)
    print("\n📡 TESTE 3: Dados parciais (sem Target)")
    print("-" * 50)
    
    radar_data_partial = """-----Human Detected-----
breath_rate: 25.50
heart_rate: 75.00
x_position: 0.25
y_position: 0.80
distance: 0.85"""
    
    result_partial = parse_serial_data(radar_data_partial)
    
    if result_partial:
        print("\n✅ TESTE 3 PASSOU!")
        print(f"   X: {result_partial.get('x_point', 0)}m")
        print(f"   Y: {result_partial.get('y_point', 0)}m")
        print(f"   ❤️: {result_partial.get('heart_rate', 0)} BPM")
        print(f"   🫁: {result_partial.get('breath_rate', 0)} resp/min")
        print(f"   🏃: {result_partial.get('move_speed', 0)} m/s")
        print(f"   📏: {result_partial.get('distance', 0)}m")
    else:
        print("\n❌ TESTE 3 FALHOU!")
    
    # Teste 4: Dados corrompidos
    print("\n📡 TESTE 4: Dados corrompidos")
    print("-" * 50)
    
    radar_data_corrupt = """-----Human Detected-----
breath_rate: abc
heart_rate: def
x_position: ghi
y_position: jkl
distance: mno"""
    
    result_corrupt = parse_serial_data(radar_data_corrupt)
    
    if result_corrupt:
        print("\n✅ TESTE 4 PASSOU!")
        print(f"   X: {result_corrupt.get('x_point', 0)}m")
        print(f"   Y: {result_corrupt.get('y_point', 0)}m")
        print(f"   ❤️: {result_corrupt.get('heart_rate', 0)} BPM")
        print(f"   🫁: {result_corrupt.get('breath_rate', 0)} resp/min")
        print(f"   🏃: {result_corrupt.get('move_speed', 0)} m/s")
        print(f"   📏: {result_corrupt.get('distance', 0)}m")
    else:
        print("\n❌ TESTE 4 FALHOU!")
    
    print("\n" + "=" * 60)
    print("🏁 TESTES CONCLUÍDOS!")

if __name__ == "__main__":
    test_parser()
