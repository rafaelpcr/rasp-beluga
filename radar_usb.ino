#include <Arduino.h>
#include "Seeed_Arduino_mmWave.h"

// Configuração da comunicação serial
HardwareSerial mmWaveSerial(0);
SEEED_MR60BHA2 mmWave;

// Variáveis para dados do sensor
float breath_rate = 0;
float heart_rate = 0;
float distance = 0;
float x_position = 0;
float y_position = 0;
float move_speed = 0;

// Estrutura para dados de posição (usando a API correta da nova biblioteca)
PeopleCounting target_info;

// Contador de loops para debug
unsigned long loop_count = 0;

void setup() {
  Serial.begin(115200);
  delay(1000);
  
  Serial.println("=== RADAR SIMPLIFICADO ===");
  Serial.println("Inicializando sensor MR60BHA2...");
  
  // Inicializa comunicação serial com sensor
  mmWaveSerial.begin(115200);
  delay(1000);
  
  // Inicializa sensor
  mmWave.begin(&mmWaveSerial);
  Serial.println("Sensor inicializado!");
  
  Serial.println("Aguardando dados...");
  Serial.println("========================");
}

void loop() {
  loop_count++;
  
  // Atualiza dados do sensor
  if (mmWave.update(1000)) {
    // Obtém dados básicos
    mmWave.getBreathRate(breath_rate);
    mmWave.getHeartRate(heart_rate);
    mmWave.getDistance(distance);
    
    // Obtém dados de posição usando a função correta da nova biblioteca
    if (mmWave.getPeopleCountingTargetInfo(target_info) && target_info.targets.size() > 0) {
      const auto& target = target_info.targets[0];
      x_position = target.x_point;
      y_position = target.y_point;
      move_speed = abs(target.dop_index) * 1.0; // Converte para cm/s
    } else {
      x_position = 0;
      y_position = 0;
      move_speed = 0;
    }
    
    // Envia dados formatados
    Serial.println("-----Human Detected-----");
    Serial.printf("breath_rate: %.2f\n", breath_rate);
    Serial.printf("heart_rate: %.2f\n", heart_rate);
    Serial.printf("x_position: %.2f\n", x_position);
    Serial.printf("y_position: %.2f\n", y_position);
    Serial.printf("distance: %.2f\n", distance);
    
    if (target_info.targets.size() > 0) {
      Serial.println("Target 1:");
      Serial.printf("  x_point: %.2f\n", x_position);
      Serial.printf("  y_point: %.2f\n", y_position);
      Serial.printf("  dop_index: %d\n", target_info.targets[0].dop_index);
      Serial.printf("  cluster_index: %d\n", target_info.targets[0].cluster_index);
      Serial.printf("  move_speed: %.2f cm/s\n", move_speed);
    }
    
    Serial.println(); // Linha em branco para separar leituras
  } else {
    // Falha na leitura
    Serial.printf("Loop %lu: Falha na leitura do sensor\n", loop_count);
  }
  
  // Delay entre leituras
  delay(500);
} 
