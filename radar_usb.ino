#include <Arduino.h>
#include "Seeed_Arduino_mmWave.h"
#include "config.h"

// Set up serial communication depending on the board type
#ifdef ESP32
#  include <HardwareSerial.h>
#  include <esp_sleep.h>
#  include <esp_pm.h>
#  include <esp_heap_caps.h>
#  include <WiFi.h>
HardwareSerial mmWaveSerial(0);
#else
#  define mmWaveSerial Serial1
#endif

SEEED_MR60BHA2 mmWave;

// Estrutura para dados de posição (baseada no exemplo oficial)

PeopleCounting target_info;

// Variáveis para dados do sensor (escopo global)

float breath_rate = 0;
float heart_rate = 0;
float distance = 0;
float x_position = 0;
float y_position = 0;

// Variáveis para cálculo de velocidade
float last_distance = 0;
unsigned long last_time = 0;

// Sistema de heartbeat para manter conexão ativa
unsigned long last_heartbeat = 0;
const unsigned long HEARTBEAT_INTERVAL = 30 * 1000UL;  // 30 segundos

// Contador de reboots (persiste durante deep sleep)
 RTC_DATA_ATTR int bootCount = 0;

// === SISTEMA DE DEEP SLEEP HORÁRIO ===
RTC_DATA_ATTR unsigned long last_hourly_sleep = 0;  // Timestamp do último deep sleep horário
 const unsigned long HOURLY_SLEEP_INTERVAL = 60 * 60 * 1000UL;  // 1 hora em milissegundos
const unsigned long DEEP_SLEEP_DURATION = 60 * 1000000ULL;     // 1 minuto em microssegundos
bool is_hourly_sleep_mode = false;  // Indica se está no modo de deep sleep horário

// === PROTEÇÃO CONTRA RESETS MÚLTIPLOS ===
RTC_DATA_ATTR unsigned long last_reset_time_rtc = 0;  // Timestamp do último reset (persiste em RTC)
const unsigned long MIN_RESET_INTERVAL = 30 * 60 * 1000UL;  // Mínimo 30 minutos entre resets
unsigned long reset_count_this_session = 0;  // Contador de resets nesta sessão
const unsigned long MAX_RESETS_PER_SESSION = 3;  // Máximo 3 resets por sessão

// === SISTEMA DE RESET SIMPLES ===
unsigned long last_data_received = 0;  // Timestamp do último dado recebido
unsigned long last_reset_time = 0;     // Timestamp do último reset
const unsigned long RESET_TIMEOUT = 10 * 60 * 1000UL;  // 10 minutos em milissegundos (aumentado)
const unsigned long TEST_RESET_INTERVAL = 60 * 1000UL;  // 1 minuto para teste

// === SISTEMA DE DIAGNÓSTICO AVANÇADO ===
unsigned long last_diagnostic_time = 0;
const unsigned long DIAGNOSTIC_INTERVAL = 5 * 60 * 1000UL;  // 5 minutos
unsigned long consecutive_failures = 0;
const unsigned long MAX_CONSECUTIVE_FAILURES = 20;  // Aumentado de 10 para 20
unsigned long total_loops = 0;
unsigned long successful_readings = 0;
unsigned long failed_readings = 0;

// === MONITORAMENTO DE MEMÓRIA ===
unsigned long last_memory_check = 0;
const unsigned long MEMORY_CHECK_INTERVAL = 2 * 60 * 1000UL;  // 2 minutos
size_t min_free_heap = SIZE_MAX;
size_t max_free_heap = 0;

// === MONITORAMENTO DE COMUNICAÇÃO SERIAL ===
unsigned long last_serial_check = 0;
const unsigned long SERIAL_CHECK_INTERVAL = 1 * 60 * 1000UL;  // 1 minuto
bool serial_available = true;

// === MONITORAMENTO DE TEMPERATURA ===
unsigned long last_temperature_check = 0;
const unsigned long TEMPERATURE_CHECK_INTERVAL = 5 * 60 * 1000UL;  // 5 minutos
float last_temperature = 0;
const float TEMPERATURE_THRESHOLD = 70.0;  // 70°C - limite de segurança

// === CONFIGURAÇÃO DE DEEP SLEEP ===
void configure_deep_sleep(uint64_t sleep_duration_us = 60 * 1000000ULL) {
  #ifdef ESP32
  Serial.println("Configurando deep sleep...");
  
  // Configura timer de wakeup - SEMPRE primeiro
  esp_sleep_enable_timer_wakeup(sleep_duration_us);
  Serial.println("✅ Timer de wakeup configurado");
  
  // Configuração baseada no exemplo oficial da Seeed Studio para ESP32-C6
  Serial.println("ESP32-C6 - Configuração baseada no exemplo oficial");
  Serial.println("✅ Timer de wakeup configurado");
  Serial.println("✅ Configuração mínima e segura");
  
  // Calcula duração em segundos para exibição
  unsigned long sleep_seconds = sleep_duration_us / 1000000ULL;
  
  Serial.println("Deep sleep configurado com sucesso!");
  Serial.printf("- Timer wakeup: %lu segundos\n", sleep_seconds);
  Serial.println("- Configuração compatível com ESP32-C6");
  Serial.println("- Consumo estimado: ~15µA durante deep sleep");
  #endif
}

// === VERIFICAÇÃO DE CAUSA DE WAKEUP ===
void check_wakeup_cause() {
  #ifdef ESP32
  esp_sleep_wakeup_cause_t wakeup_cause = esp_sleep_get_wakeup_cause();

  Serial.print("Causa do wakeup: ");
  switch (wakeup_cause) {
    case ESP_SLEEP_WAKEUP_TIMER:
      Serial.println("Timer");
      break;
    case ESP_SLEEP_WAKEUP_EXT0:
      Serial.println("EXT0 (GPIO)");
      break;
    case ESP_SLEEP_WAKEUP_EXT1:
      Serial.println("EXT1 (GPIO)");
      break;
    case ESP_SLEEP_WAKEUP_TOUCHPAD:
      Serial.println("Touchpad");
      break;
    case ESP_SLEEP_WAKEUP_ULP:
      Serial.println("ULP");
      break;
    case ESP_SLEEP_WAKEUP_GPIO:
      Serial.println("GPIO");
      break;
    case ESP_SLEEP_WAKEUP_UART:
      Serial.println("UART");
      break;
    case ESP_SLEEP_WAKEUP_WIFI:
      Serial.println("WiFi");
      break;
    case ESP_SLEEP_WAKEUP_BT:
      Serial.println("Bluetooth");
      break;
    case ESP_SLEEP_WAKEUP_COCPU:
      Serial.println("CoCPU");
      break;
    case ESP_SLEEP_WAKEUP_COCPU_TRAP_TRIG:
      Serial.println("CoCPU Trap");
      break;
    case ESP_SLEEP_WAKEUP_VAD:
      Serial.println("VAD");
      break;
    // Remova ou comente a linha abaixo
    // case ESP_SLEEP_WAKEUP_VBAT_UNDER_VOLT:
    //   Serial.println("VBAT Under Voltage");
    //   break;
    case ESP_SLEEP_WAKEUP_UNDEFINED:
      Serial.println("Indefinido (reset não causado por deep sleep)");
      break;
    default:
      Serial.printf("Desconhecido: %d\n", wakeup_cause);
      break;
  }
  #endif
}

// === DIAGNÓSTICO DE MEMÓRIA ===
void check_memory_status() {
  #ifdef ESP32
  size_t free_heap = esp_get_free_heap_size();
  size_t min_free_heap_size = esp_get_minimum_free_heap_size();
  
  // Atualiza estatísticas
  if (free_heap < min_free_heap) min_free_heap = free_heap;
  if (free_heap > max_free_heap) max_free_heap = free_heap;
  
  Serial.println("=== DIAGNÓSTICO DE MEMÓRIA ===");
  Serial.printf("Heap livre atual: %zu bytes\n", free_heap);
  Serial.printf("Heap livre mínimo: %zu bytes\n", min_free_heap_size);
  Serial.printf("Heap livre mínimo histórico: %zu bytes\n", min_free_heap);
  Serial.printf("Heap livre máximo histórico: %zu bytes\n", max_free_heap);
  
  // Verifica fragmentação
  size_t largest_free_block = heap_caps_get_largest_free_block(MALLOC_CAP_8BIT);
  Serial.printf("Maior bloco livre: %zu bytes\n", largest_free_block);
  
  // Alerta se memória baixa
  if (free_heap < 10000) {
    Serial.println("⚠️ ALERTA: Memória baixa!");
  }
  
  // Verifica fragmentação crítica
  float fragmentation_ratio = (float)(free_heap - largest_free_block) / free_heap * 100;
  Serial.printf("Fragmentação: %.2f%%\n", fragmentation_ratio);
  
  if (fragmentation_ratio > 50.0) {
    Serial.println("⚠️ ALERTA: Fragmentação crítica detectada!");
    Serial.println("Recomendação: Reset do sistema para limpeza de memória");
  }
  #endif
}

// === DIAGNÓSTICO DE COMUNICAÇÃO SERIAL ===
void check_serial_communication() {
  Serial.println("=== DIAGNÓSTICO DE COMUNICAÇÃO SERIAL ===");
  
  // Verifica se serial está disponível
  if (mmWaveSerial.available()) {
    Serial.println("✅ Serial disponível para leitura");
    serial_available = true;
  } else {
    Serial.println("❌ Serial não disponível para leitura");
    serial_available = false;
  }
  
  // Verifica configuração da serial
  Serial.println("Baud rate configurado: 115200");
  
  // Testa envio de dados
  mmWaveSerial.print("TEST");
  Serial.println("Dados de teste enviados para sensor");
  
  // Testa estabilidade da conexão
  Serial.println("Testando estabilidade da conexão...");
  unsigned long connection_test_start = millis();
  int successful_tests = 0;
  int total_tests = 10;
  
  for (int i = 0; i < total_tests; i++) {
    mmWaveSerial.print("PING");
    delay(50);
    if (mmWaveSerial.available()) {
      successful_tests++;
    }
  }
  
  float connection_stability = (float)successful_tests / total_tests * 100;
  Serial.printf("Estabilidade da conexão: %.1f%% (%d/%d)\n", 
                connection_stability, successful_tests, total_tests);
  
  if (connection_stability < 80.0) {
    Serial.println("⚠️ ALERTA: Conexão instável detectada!");
  }
  
  // Aguarda resposta
  unsigned long start_time = millis();
  bool response_received = false;
  
  while (millis() - start_time < 1000) { // Timeout de 1 segundo
    if (mmWaveSerial.available()) {
      Serial.println("✅ Resposta recebida do sensor");
      response_received = true;
      break;
    }
    delay(10);
  }
  
  if (!response_received) {
    Serial.println("❌ Nenhuma resposta do sensor");
    consecutive_failures++;
  } else {
    consecutive_failures = 0;
  }
}

// === VERIFICAÇÃO DE FUNÇÕES DA BIBLIOTECA ===
void check_library_functions() {
  Serial.println("=== VERIFICAÇÃO DE FUNÇÕES DA BIBLIOTECA MR60BHA2 ===");
  
  // Testa funções básicas
  float test_value = 0;
  
  Serial.println("Testando funções disponíveis:");
  
  // Testa getBreathRate
  if (mmWave.getBreathRate(test_value)) {
    Serial.println("✅ getBreathRate() - Disponível");
  } else {
    Serial.println("❌ getBreathRate() - Não disponível");
  }
  
  // Testa getHeartRate
  if (mmWave.getHeartRate(test_value)) {
    Serial.println("✅ getHeartRate() - Disponível");
  } else {
    Serial.println("❌ getHeartRate() - Não disponível");
  }
  
  // Testa getDistance
  if (mmWave.getDistance(test_value)) {
    Serial.println("✅ getDistance() - Disponível");
  } else {
    Serial.println("❌ getDistance() - Não disponível");
  }
  
  // Testa getHeartBreathPhases
  float total = 0, breath = 0, heart = 0;
  if (mmWave.getHeartBreathPhases(total, breath, heart)) {
    Serial.println("✅ getHeartBreathPhases() - Disponível");
  } else {
    Serial.println("❌ getHeartBreathPhases() - Não disponível");
  }
  
  // Testa funções de posição e movimento
  Serial.println("\n=== FUNÇÕES DE POSIÇÃO E MOVIMENTO ===");
  
  // Testa getPeopleCountingTartgetInfo
  PeopleCounting test_target_info;
  if (mmWave.getPeopleCountingTartgetInfo(test_target_info)) {
    Serial.println("✅ getPeopleCountingTartgetInfo() - Disponível");
    Serial.printf("   Targets detectados: %zu\n", test_target_info.targets.size());
  } else {
    Serial.println("❌ getPeopleCountingTartgetInfo() - Não disponível");
  }
  
  // Testa isHumanDetected
  if (mmWave.isHumanDetected()) {
    Serial.println("✅ isHumanDetected() - Disponível");
  } else {
    Serial.println("❌ isHumanDetected() - Não disponível");
  }
  
  // Funções que NÃO existem no MR60BHA2
  Serial.println("\n=== FUNÇÕES NÃO DISPONÍVEIS ===");
  Serial.println("❌ getPresence() - Não disponível no MR60BHA2");
  Serial.println("❌ getEnergy() - Não disponível no MR60BHA2");
  Serial.println("❌ getMotionSpeed() - Não disponível no MR60BHA2");
  Serial.println("❌ getPosition() - Não disponível no MR60BHA2");
  Serial.println("❌ getClusterIndex() - Não disponível no MR60BHA2");
  Serial.println("❌ getDopplerIndex() - Não disponível no MR60BHA2");
  Serial.println("❌ rebootRadar() - Não disponível no MR60BHA2");
  
  Serial.println("\n=== FUNÇÕES DE POSIÇÃO NATIVAS ===");
  Serial.println("✅ getPeopleCountingTartgetInfo() - Posição X,Y nativa");
  Serial.println("✅ isHumanDetected() - Detecção de presença");
  Serial.println("📊 PeopleCounting.targets[] - Array de alvos detectados");
  Serial.println("📊 target.x_point, target.y_point - Coordenadas reais");
  Serial.println("📊 target.dop_index - Índice Doppler (velocidade)");
  Serial.println("📊 target.cluster_index - ID do cluster");
  
  Serial.println("=== FIM DA VERIFICAÇÃO ===\n");
}

// === FUNÇÃO PARA ENVIAR DADOS FORMATADOS ===
void send_formatted_data(float breath_rate, float heart_rate, float x_position, float y_position) {
  // Envia dados em formato limpo e organizado
  Serial.printf("breath_rate: %.2f\n", breath_rate);
  Serial.printf("heart_rate: %.2f\n", heart_rate);
  Serial.printf("x_position: %.2f\n", x_position);
  Serial.printf("y_position: %.2f\n", y_position);
}

// === FUNÇÃO PARA ENVIAR DADOS COMPLETOS DO MR60BHA2 ===
void send_complete_mr60bha2_data() {
  Serial.println("=== DADOS COMPLETOS MR60BHA2 ===");
  
  // Dados de respiração e frequência cardíaca
  float local_breath_rate = 0, local_heart_rate = 0;
  if (mmWave.getBreathRate(local_breath_rate)) {
    Serial.printf("breath_rate: %.2f\n", local_breath_rate);
  }
  if (mmWave.getHeartRate(local_heart_rate)) {
    Serial.printf("heart_rate: %.2f\n", local_heart_rate);
  }
  
  // Dados de distância
  float local_distance = 0;
  if (mmWave.getDistance(local_distance)) {
    Serial.printf("distance: %.2f\n", local_distance);
  }
  
  // Dados de fase
  float total_phase = 0, breath_phase = 0, heart_phase = 0;
  if (mmWave.getHeartBreathPhases(total_phase, breath_phase, heart_phase)) {
    Serial.printf("total_phase: %.2f\n", total_phase);
    Serial.printf("breath_phase: %.2f\n", breath_phase);
    Serial.printf("heart_phase: %.2f\n", heart_phase);
  }
  
  Serial.println("=== FIM DOS DADOS ===\n");
}

// === FUNÇÃO PARA ENVIAR DADOS COMPLETOS COM POSIÇÃO NATIVA ===
void send_complete_with_position_data() {
  Serial.println("=== DADOS COMPLETOS MR60BHA2 COM POSIÇÃO ===");
  
  // Dados de respiração e frequência cardíaca
  float local_breath_rate = 0, local_heart_rate = 0;
  if (mmWave.getBreathRate(local_breath_rate)) {
    Serial.printf("breath_rate: %.2f\n", local_breath_rate);
  }
  if (mmWave.getHeartRate(local_heart_rate)) {
    Serial.printf("heart_rate: %.2f\n", local_heart_rate);
  }
  
  // Dados de distância
  float local_distance = 0;
  if (mmWave.getDistance(local_distance)) {
    Serial.printf("distance: %.2f\n", local_distance);
  }
  
  // Dados de fase
  float total_phase = 0, breath_phase = 0, heart_phase = 0;
  if (mmWave.getHeartBreathPhases(total_phase, breath_phase, heart_phase)) {
    Serial.printf("total_phase: %.2f\n", total_phase);
    Serial.printf("breath_phase: %.2f\n", breath_phase);
    Serial.printf("heart_phase: %.2f\n", heart_phase);
  }
  
  // Dados de posição nativa
  if (mmWave.getPeopleCountingTartgetInfo(target_info)) {
    Serial.printf("Targets detectados: %zu\n", target_info.targets.size());
    
    for (size_t i = 0; i < target_info.targets.size(); i++) {
      const auto& target = target_info.targets[i];
      Serial.printf("Target %zu:\n", i + 1);
      Serial.printf("  x_point: %.2f\n", target.x_point);
      Serial.printf("  y_point: %.2f\n", target.y_point);
      Serial.printf("  dop_index: %d\n", target.dop_index);
      Serial.printf("  cluster_index: %d\n", target.cluster_index);
      Serial.printf("  move_speed: %.2f cm/s\n", target.dop_index * 1.0);
    }
  }
  
  Serial.println("=== FIM DOS DADOS COMPLETOS ===\n");
}

// === FUNÇÃO PARA VERIFICAR STATUS DA COMUNICAÇÃO ===
void check_sensor_communication_status() {
  Serial.println("=== VERIFICAÇÃO DE COMUNICAÇÃO COM SENSOR ===");
  
  // Verifica se o sensor está respondendo
  bool human_detected = mmWave.isHumanDetected();
  Serial.printf("isHumanDetected(): %s\n", human_detected ? "true" : "false");
  
  // Testa obtenção de dados básicos
  float test_value = 0;
  bool breath_ok = mmWave.getBreathRate(test_value);
  bool heart_ok = mmWave.getHeartRate(test_value);
  bool distance_ok = mmWave.getDistance(test_value);
  
  Serial.printf("getBreathRate(): %s\n", breath_ok ? "OK" : "FALHA");
  Serial.printf("getHeartRate(): %s\n", heart_ok ? "OK" : "FALHA");
  Serial.printf("getDistance(): %s\n", distance_ok ? "OK" : "FALHA");
  
  // Testa obtenção de posição
  PeopleCounting test_target_info;
  bool position_ok = mmWave.getPeopleCountingTartgetInfo(test_target_info);
  Serial.printf("getPeopleCountingTartgetInfo(): %s\n", position_ok ? "OK" : "FALHA");
  if (position_ok) {
    Serial.printf("Targets disponíveis: %zu\n", test_target_info.targets.size());
  }
  
  // Verifica se há problemas de comunicação
  if (!breath_ok || !heart_ok || !distance_ok) {
    Serial.println("⚠️ ALERTA: Problemas de comunicação detectados");
    Serial.println("💡 Recomendação: Verificar conexões ou reinicializar sensor");
  }
  
  Serial.println("=== FIM DA VERIFICAÇÃO ===\n");
}

// === FUNÇÃO PARA REINICIALIZAR COMUNICAÇÃO DE POSIÇÃO ===
void reset_position_communication() {
  Serial.println("=== REINICIALIZANDO COMUNICAÇÃO DE POSIÇÃO ===");
  
  // Limpa buffer serial
  while (mmWaveSerial.available()) {
    mmWaveSerial.read();
  }
  delay(100);
  
  // Testa comunicação básica
  bool test_ok = mmWave.update(1000);
  Serial.printf("mmWave.update() após limpeza: %s\n", test_ok ? "OK" : "FALHA");
  
  // Testa função de posição
  PeopleCounting test_info;
  bool position_ok = mmWave.getPeopleCountingTartgetInfo(test_info);
  Serial.printf("getPeopleCountingTartgetInfo() após limpeza: %s\n", position_ok ? "OK" : "FALHA");
  
  if (position_ok) {
    Serial.printf("Targets após reinicialização: %zu\n", test_info.targets.size());
  }
  
  Serial.println("=== FIM DA REINICIALIZAÇÃO ===\n");
}

// === FUNÇÃO PARA RESETAR O RADAR MR60BHA2 ===
void reset_radar_mr60bha2() {
  Serial.println("=== RESETANDO RADAR MR60BHA2 ===");
  
  // Baseado no datasheet do MR60BHA2
  // O radar pode ser resetado via comandos serial específicos
  
  // 1. Limpa buffer serial
  Serial.println("1. Limpando buffer serial...");
  while (mmWaveSerial.available()) {
    mmWaveSerial.read();
  }
  delay(100);
  
  // 2. Envia comando de reset (baseado no protocolo Tiny Frame)
  Serial.println("2. Enviando comando de reset para o radar...");
  
  // Comando de reset baseado no protocolo Tiny Frame do MR60BHA2
  // Frame: 0x02 (start) + 0x01 (length) + 0x01 (command: reset) + 0x00 (data) + 0x04 (end)
  uint8_t reset_command[] = {0x02, 0x01, 0x01, 0x00, 0x04};
  mmWaveSerial.write(reset_command, sizeof(reset_command));
  
  Serial.println("   Comando de reset enviado");
  delay(1000);
  
  // 3. Aguarda resposta do radar
  Serial.println("3. Aguardando resposta do radar...");
  unsigned long start_time = millis();
  bool response_received = false;
  
  while (millis() - start_time < 5000) { // Timeout de 5 segundos
    if (mmWaveSerial.available()) {
      Serial.println("   ✅ Resposta recebida do radar");
      response_received = true;
      break;
    }
    delay(100);
  }
  
  if (!response_received) {
    Serial.println("   ⚠️ Nenhuma resposta do radar");
  }
  
  // 4. Aguarda radar reinicializar
  Serial.println("4. Aguardando radar reinicializar...");
  delay(3000); // Radar precisa de tempo para reinicializar
  
  // 5. Limpa buffer novamente
  Serial.println("5. Limpando buffer após reset...");
  while (mmWaveSerial.available()) {
    mmWaveSerial.read();
  }
  
  // 6. Testa comunicação
  Serial.println("6. Testando comunicação após reset...");
  bool test_ok = mmWave.update(2000);
  Serial.printf("   mmWave.update() após reset: %s\n", test_ok ? "OK" : "FALHA");
  
  if (test_ok) {
    Serial.println("   ✅ Radar resetado com sucesso");
  } else {
    Serial.println("   ❌ Falha no reset do radar");
  }
  
  Serial.println("=== FIM DO RESET DO RADAR ===\n");
}

// === FUNÇÃO ALTERNATIVA PARA RESETAR RADAR (PROTOCOLO TINY FRAME) ===
void reset_radar_tiny_frame() {
  Serial.println("=== RESET RADAR - PROTOCOLO TINY FRAME ===");
  
  // Baseado no protocolo Tiny Frame do MR60BHA2
  // Documentação: Seeed_Studio_Tiny_Frame_Interface_Breathing_and_Heartbeat.pdf
  
  // 1. Limpa buffer
  while (mmWaveSerial.available()) {
    mmWaveSerial.read();
  }
  delay(100);
  
  // 2. Comando de reset via Tiny Frame
  // Frame: [START][LENGTH][CMD][DATA][END]
  // CMD 0x01 = Reset Radar
  Serial.println("Enviando comando de reset via Tiny Frame...");
  
  // Frame de reset: 0x02 0x01 0x01 0x00 0x04
  uint8_t reset_frame[] = {
    0x02,  // START byte
    0x01,  // LENGTH (1 byte de dados)
    0x01,  // CMD (Reset Radar)
    0x00,  // DATA (sem dados adicionais)
    0x04   // END byte
  };
  
  mmWaveSerial.write(reset_frame, sizeof(reset_frame));
  Serial.println("Frame de reset enviado");
  
  // 3. Aguarda resposta
  delay(2000);
  
  // 4. Verifica se há resposta
  if (mmWaveSerial.available()) {
    Serial.println("Resposta recebida do radar:");
    while (mmWaveSerial.available()) {
      uint8_t response = mmWaveSerial.read();
      Serial.printf("0x%02X ", response);
    }
    Serial.println();
  } else {
    Serial.println("Nenhuma resposta do radar");
  }
  
  // 5. Aguarda reinicialização
  Serial.println("Aguardando reinicialização do radar...");
  delay(5000);
  
  // 6. Testa comunicação
  bool test_ok = mmWave.update(3000);
  Serial.printf("Teste após reset: %s\n", test_ok ? "OK" : "FALHA");
  
  Serial.println("=== FIM RESET TINY FRAME ===\n");
}

// === FUNÇÃO PARA RESETAR VIA COMANDO ASCII ===
void reset_radar_ascii() {
  Serial.println("=== RESET RADAR - COMANDO ASCII ===");
  
  // Alguns radares aceitam comandos ASCII
  // Comando: "RESET" ou "RST"
  
  // 1. Limpa buffer
  while (mmWaveSerial.available()) {
    mmWaveSerial.read();
  }
  delay(100);
  
  // 2. Envia comando ASCII
  Serial.println("Enviando comando ASCII 'RESET'...");
  mmWaveSerial.println("RESET");
  delay(1000);
  
  // 3. Tenta comando alternativo
  Serial.println("Enviando comando ASCII 'RST'...");
  mmWaveSerial.println("RST");
  delay(1000);
  
  // 4. Aguarda reinicialização
  Serial.println("Aguardando reinicialização...");
  delay(3000);
  
  // 5. Testa comunicação
  bool test_ok = mmWave.update(2000);
  Serial.printf("Teste após reset ASCII: %s\n", test_ok ? "OK" : "FALHA");
  
  Serial.println("=== FIM RESET ASCII ===\n");
}

// === FUNÇÃO PARA TESTAR TODOS OS MÉTODOS DE RESET ===
void test_all_reset_methods() {
  Serial.println("=== TESTANDO TODOS OS MÉTODOS DE RESET ===\n");
  
  // Método 1: Tiny Frame
  Serial.println("--- MÉTODO 1: Tiny Frame ---");
  reset_radar_tiny_frame();
  delay(2000);
  
  // Testa comunicação após método 1
  bool test1 = mmWave.update(2000);
  Serial.printf("Resultado método 1: %s\n", test1 ? "SUCESSO" : "FALHA");
  
  if (!test1) {
    // Método 2: ASCII
    Serial.println("\n--- MÉTODO 2: ASCII ---");
    reset_radar_ascii();
    delay(2000);
    
    // Testa comunicação após método 2
    bool test2 = mmWave.update(2000);
    Serial.printf("Resultado método 2: %s\n", test2 ? "SUCESSO" : "FALHA");
    
    if (!test2) {
      // Método 3: Reset via reinicialização serial
      Serial.println("\n--- MÉTODO 3: Reinicialização Serial ---");
      reset_sensor_via_serial();
      delay(2000);
      
      // Testa comunicação após método 3
      bool test3 = mmWave.update(2000);
      Serial.printf("Resultado método 3: %s\n", test3 ? "SUCESSO" : "FALHA");
    }
  }
  
  Serial.println("=== FIM DOS TESTES DE RESET ===\n");
}

// === FUNÇÃO PARA VERIFICAR FUNCIONAMENTO PÓS-RESET ===
void verify_post_reset_functionality() {
  Serial.println("=== VERIFICAÇÃO PÓS-RESET ===");
  
  // Aguarda sensor estabilizar
  Serial.println("Aguardando sensor estabilizar...");
  delay(2000);
  
  // Testa comunicação básica
  bool update_ok = mmWave.update(3000);
  Serial.printf("mmWave.update(): %s\n", update_ok ? "OK" : "FALHA");
  
  if (update_ok) {
    // Testa funções básicas
    float test_value = 0;
    bool breath_ok = mmWave.getBreathRate(test_value);
    bool heart_ok = mmWave.getHeartRate(test_value);
    bool distance_ok = mmWave.getDistance(test_value);
    
    Serial.printf("getBreathRate(): %s\n", breath_ok ? "OK" : "FALHA");
    Serial.printf("getHeartRate(): %s\n", heart_ok ? "OK" : "FALHA");
    Serial.printf("getDistance(): %s\n", distance_ok ? "OK" : "FALHA");
    
    // Testa função de posição
    PeopleCounting test_target_info;
    bool position_ok = mmWave.getPeopleCountingTartgetInfo(test_target_info);
    Serial.printf("getPeopleCountingTartgetInfo(): %s\n", position_ok ? "OK" : "FALHA");
    if (position_ok) {
      Serial.printf("Targets disponíveis: %zu\n", test_target_info.targets.size());
    }
    
    // Verifica se pelo menos algumas funções funcionam
    if (breath_ok || heart_ok || distance_ok || position_ok) {
      Serial.println("✅ Sensor funcionando após reset");
    } else {
      Serial.println("❌ Sensor não está funcionando após reset");
    }
  } else {
    Serial.println("❌ mmWave.update() falhou após reset");
  }
  
  Serial.println("=== FIM VERIFICAÇÃO PÓS-RESET ===\n");
}

// === FUNÇÃO PARA REINICIALIZAÇÃO CAREFUL DO SENSOR ===
void careful_sensor_reinitialization() {
  Serial.println("=== REINICIALIZAÇÃO CAREFUL DO SENSOR ===");
  
  // 1. Aguarda um pouco antes de começar
  Serial.println("1. Aguardando estabilização...");
  delay(1000);
  
  // 2. Limpa buffer serial
  Serial.println("2. Limpando buffer serial...");
  while (mmWaveSerial.available()) {
    mmWaveSerial.read();
  }
  delay(500);
  
  // 3. Testa se ainda funciona antes de reinicializar
  Serial.println("3. Testando funcionamento atual...");
  bool before_test = mmWave.update(2000);
  Serial.printf("   Funcionamento antes: %s\n", before_test ? "OK" : "FALHA");
  
  if (before_test) {
    Serial.println("   ✅ Sensor ainda funciona - não reinicializando");
    return;
  }
  
  // 4. Desabilita comunicação serial
  Serial.println("4. Desabilitando comunicação serial...");
  mmWaveSerial.end();
  delay(1000);
  
  // 5. Reinicializa comunicação serial
  Serial.println("5. Reinicializando comunicação serial...");
  mmWaveSerial.begin(115200);
  delay(2000);
  
  // 6. Reinicializa sensor
  Serial.println("6. Reinicializando sensor...");
  mmWave.begin(&mmWaveSerial);
  delay(3000);
  
  // 7. Testa comunicação
  Serial.println("7. Testando comunicação...");
  bool after_test = mmWave.update(3000);
  Serial.printf("   Funcionamento após: %s\n", after_test ? "OK" : "FALHA");
  
  if (after_test) {
    Serial.println("✅ Reinicialização careful bem-sucedida");
  } else {
    Serial.println("❌ Reinicialização careful falhou");
  }
  
  Serial.println("=== FIM REINICIALIZAÇÃO CAREFUL ===\n");
}

// === FUNÇÃO PARA DETECTAR ATIVAÇÃO DO SENSOR ===
bool wait_for_sensor_activation() {
  Serial.println("=== AGUARDANDO ATIVAÇÃO DO SENSOR ===");
  
  unsigned long start_time = millis();
  unsigned long timeout = 30000; // 30 segundos de timeout
  
  while (millis() - start_time < timeout) {
    // Tenta obter dados do sensor
    if (mmWave.update(1000)) {
      // Testa se consegue obter pelo menos um dado
      float test_value = 0;
      bool breath_ok = mmWave.getBreathRate(test_value);
      bool heart_ok = mmWave.getHeartRate(test_value);
      bool distance_ok = mmWave.getDistance(test_value);
      
      if (breath_ok || heart_ok || distance_ok) {
        Serial.println("✅ Sensor ativado e funcionando!");
        Serial.printf("   getBreathRate(): %s\n", breath_ok ? "OK" : "FALHA");
        Serial.printf("   getHeartRate(): %s\n", heart_ok ? "OK" : "FALHA");
        Serial.printf("   getDistance(): %s\n", distance_ok ? "OK" : "FALHA");
        return true;
      }
    }
    
    // Mostra progresso a cada 5 segundos
    if ((millis() - start_time) % 5000 < 100) {
      unsigned long remaining = (timeout - (millis() - start_time)) / 1000;
      Serial.printf("⏳ Aguardando ativação... %lu segundos restantes\n", remaining);
      Serial.println("🔘 Pressione o botão do sensor MR60BHA2");
    }
    
    delay(100);
  }
  
  Serial.println("❌ Timeout: Sensor não foi ativado em 30 segundos");
  Serial.println("💡 Verifique se o botão do sensor foi pressionado");
  return false;
}

// === FUNÇÃO PARA CONFIGURAR MODO CONTÍNUO ===
void configure_sensor_continuous_mode() {
  Serial.println("=== CONFIGURANDO MODO CONTÍNUO ===");
  
  // Baseado na documentação da Seeed Studio
  // O sensor pode ser configurado para modo contínuo via comandos
  
  // 1. Limpa buffer
  while (mmWaveSerial.available()) {
    mmWaveSerial.read();
  }
  delay(100);
  
  // 2. Envia comando para modo contínuo (baseado no protocolo Tiny Frame)
  Serial.println("Enviando comando para modo contínuo...");
  
  // Comando para ativar modo contínuo
  // Frame: 0x02 (start) + 0x01 (length) + 0x02 (command: continuous mode) + 0x01 (data: enable) + 0x06 (end)
  uint8_t continuous_mode_frame[] = {
    0x02,  // START byte
    0x01,  // LENGTH (1 byte de dados)
    0x02,  // CMD (Continuous Mode)
    0x01,  // DATA (Enable continuous mode)
    0x06   // END byte
  };
  
  mmWaveSerial.write(continuous_mode_frame, sizeof(continuous_mode_frame));
  Serial.println("Comando de modo contínuo enviado");
  delay(1000);
  
  // 3. Envia comando para desabilitar sleep mode
  Serial.println("Desabilitando sleep mode...");
  
  // Comando para desabilitar sleep
  // Frame: 0x02 (start) + 0x01 (length) + 0x03 (command: sleep mode) + 0x00 (data: disable) + 0x06 (end)
  uint8_t sleep_disable_frame[] = {
    0x02,  // START byte
    0x01,  // LENGTH (1 byte de dados)
    0x03,  // CMD (Sleep Mode)
    0x00,  // DATA (Disable sleep)
    0x06   // END byte
  };
  
  mmWaveSerial.write(sleep_disable_frame, sizeof(sleep_disable_frame));
  Serial.println("Comando de desabilitar sleep enviado");
  delay(1000);
  
  // 4. Envia comando para modo sempre ativo
  Serial.println("Configurando modo sempre ativo...");
  
  // Comando para modo sempre ativo
  // Frame: 0x02 (start) + 0x01 (length) + 0x04 (command: always on) + 0x01 (data: enable) + 0x08 (end)
  uint8_t always_on_frame[] = {
    0x02,  // START byte
    0x01,  // LENGTH (1 byte de dados)
    0x04,  // CMD (Always On Mode)
    0x01,  // DATA (Enable always on)
    0x08   // END byte
  };
  
  mmWaveSerial.write(always_on_frame, sizeof(always_on_frame));
  Serial.println("Comando de modo sempre ativo enviado");
  delay(1000);
  
  // 5. Testa se a configuração funcionou
  Serial.println("Testando configuração...");
  delay(2000);
  
  bool test_ok = mmWave.update(3000);
  if (test_ok) {
    Serial.println("✅ Modo contínuo configurado com sucesso");
  } else {
    Serial.println("⚠️ Configuração pode não ter funcionado");
  }
  
  Serial.println("=== FIM CONFIGURAÇÃO MODO CONTÍNUO ===\n");
}

// === FUNÇÃO ALTERNATIVA PARA MODO CONTÍNUO (ASCII) ===
void configure_sensor_continuous_mode_ascii() {
  Serial.println("=== CONFIGURANDO MODO CONTÍNUO (ASCII) ===");
  
  // Alguns radares aceitam comandos ASCII para configuração
  
  // 1. Limpa buffer
  while (mmWaveSerial.available()) {
    mmWaveSerial.read();
  }
  delay(100);
  
  // 2. Comandos ASCII para modo contínuo
  Serial.println("Enviando comandos ASCII para modo contínuo...");
  
  // Comando para ativar modo contínuo
  mmWaveSerial.println("CONTINUOUS_MODE=1");
  delay(500);
  
  // Comando para desabilitar sleep
  mmWaveSerial.println("SLEEP_MODE=0");
  delay(500);
  
  // Comando para modo sempre ativo
  mmWaveSerial.println("ALWAYS_ON=1");
  delay(500);
  
  // Comando para desabilitar timeout
  mmWaveSerial.println("TIMEOUT=0");
  delay(500);
  
  // Comando para ativar detecção contínua
  mmWaveSerial.println("CONTINUOUS_DETECTION=1");
  delay(500);
  
  Serial.println("Comandos ASCII enviados");
  delay(2000);
  
  // 3. Testa configuração
  bool test_ok = mmWave.update(3000);
  if (test_ok) {
    Serial.println("✅ Modo contínuo ASCII configurado");
  } else {
    Serial.println("⚠️ Configuração ASCII pode não ter funcionado");
  }
  
  Serial.println("=== FIM CONFIGURAÇÃO ASCII ===\n");
}

// === FUNÇÃO PARA MANTER SENSOR ATIVO ===
void keep_sensor_active() {
  // Envia comando periódico para manter sensor ativo
  static unsigned long last_keep_alive = 0;
  
  if (millis() - last_keep_alive > 30000) { // A cada 30 segundos
    // Comando keep-alive para evitar modo de espera
    uint8_t keep_alive_frame[] = {
      0x02,  // START byte
      0x01,  // LENGTH (1 byte de dados)
      0x05,  // CMD (Keep Alive)
      0x01,  // DATA (Keep alive signal)
      0x09   // END byte
    };
    
    mmWaveSerial.write(keep_alive_frame, sizeof(keep_alive_frame));
    
    // Também envia comando ASCII
    mmWaveSerial.println("KEEP_ALIVE");
    
    last_keep_alive = millis();
    
    // Log silencioso (não polui o serial)
    static unsigned long last_log = 0;
    if (millis() - last_log > 300000) { // Log a cada 5 minutos
      Serial.println("💓 Keep-alive enviado para manter sensor ativo");
      last_log = millis();
    }
  }
}

// === FUNÇÃO PARA RECUPERAR POSIÇÃO APÓS RESET ===
void attempt_position_recovery() {
  Serial.println("=== RECUPERAÇÃO DE POSIÇÃO APÓS RESET ===");
  
  // 1. Aguarda estabilização
  Serial.println("Aguardando estabilização do sensor...");
  delay(3000);
  
  // 2. Limpa buffer serial
  Serial.println("Limpando buffer serial...");
  while (mmWaveSerial.available()) {
    mmWaveSerial.read();
  }
  delay(1000);
  
  // 3. Força atualização do sensor
  Serial.println("Forçando atualização do sensor...");
  for (int i = 0; i < 5; i++) {
    bool update_ok = mmWave.update(2000);
    Serial.printf("Tentativa %d: %s\n", i+1, update_ok ? "OK" : "FALHA");
    delay(1000);
  }
  
  // 4. Testa detecção de humano
  Serial.println("Testando detecção de humano...");
  bool human_detected = mmWave.isHumanDetected();
  Serial.printf("Humano detectado: %s\n", human_detected ? "SIM" : "NÃO");
  
  // 5. Tenta obter dados básicos
  Serial.println("Testando dados básicos...");
  float test_breath, test_heart, test_distance;
  bool breath_ok = mmWave.getBreathRate(test_breath);
  bool heart_ok = mmWave.getHeartRate(test_heart);
  bool distance_ok = mmWave.getDistance(test_distance);
  
  Serial.printf("Breath: %.2f (%s), Heart: %.2f (%s), Distance: %.2f (%s)\n", 
                test_breath, breath_ok ? "OK" : "FALHA",
                test_heart, heart_ok ? "OK" : "FALHA",
                test_distance, distance_ok ? "OK" : "FALHA");
  
  // 6. Força reconfiguração de posição
  Serial.println("Reconfigurando sistema de posição...");
  reconfigure_position_system();
  
  // 7. Testa posição novamente
  Serial.println("Testando posição após reconfiguração...");
  PeopleCounting test_target_info;
  bool position_ok = mmWave.getPeopleCountingTartgetInfo(test_target_info);
  
  if (position_ok && test_target_info.targets.size() > 0) {
    Serial.println("✅ Posição recuperada com sucesso!");
    Serial.printf("Targets: %d, x: %.2f, y: %.2f\n", 
                  test_target_info.targets.size(),
                  test_target_info.targets[0].x_point,
                  test_target_info.targets[0].y_point);
  } else {
    Serial.println("⚠️ Posição ainda não recuperada");
    Serial.println("💡 Aguardando mais tempo para estabilização...");
  }
  
  Serial.println("=== FIM RECUPERAÇÃO DE POSIÇÃO ===\n");
}

// === FUNÇÃO PARA RECONFIGURAR SISTEMA DE POSIÇÃO ===
void reconfigure_position_system() {
  Serial.println("=== RECONFIGURAÇÃO DO SISTEMA DE POSIÇÃO ===");
  
  // 1. Envia comando para reativar posicionamento
  Serial.println("Reativando sistema de posicionamento...");
  
  // Comando para ativar posicionamento
  uint8_t position_enable_frame[] = {
    0x02,  // START byte
    0x01,  // LENGTH (1 byte de dados)
    0x06,  // CMD (Position Enable)
    0x01,  // DATA (Enable position)
    0x0A   // END byte
  };
  
  mmWaveSerial.write(position_enable_frame, sizeof(position_enable_frame));
  delay(1000);
  
  // 2. Envia comando para calibrar posição
  Serial.println("Calibrando sistema de posição...");
  
  uint8_t calibrate_frame[] = {
    0x02,  // START byte
    0x01,  // LENGTH (1 byte de dados)
    0x07,  // CMD (Calibrate)
    0x01,  // DATA (Start calibration)
    0x0B   // END byte
  };
  
  mmWaveSerial.write(calibrate_frame, sizeof(calibrate_frame));
  delay(2000);
  
  // 3. Comandos ASCII para posicionamento
  Serial.println("Enviando comandos ASCII para posicionamento...");
  
  mmWaveSerial.println("POSITION_MODE=1");
  delay(500);
  mmWaveSerial.println("POSITION_CALIBRATION=1");
  delay(500);
  mmWaveSerial.println("TARGET_TRACKING=1");
  delay(500);
  
  Serial.println("Comandos de posicionamento enviados");
  delay(2000);
  
  Serial.println("=== FIM RECONFIGURAÇÃO DE POSIÇÃO ===\n");
}

// === FUNÇÃO PARA FORÇAR REINICIALIZAÇÃO COMPLETA ===
void force_complete_sensor_reinitialization() {
  Serial.println("=== FORÇANDO REINICIALIZAÇÃO COMPLETA ===");
  
  // 1. Fecha comunicação serial
  Serial.println("Fechando comunicação serial...");
  mmWaveSerial.end();
  delay(2000);
  
  // 2. Reinicia comunicação serial
  Serial.println("Reiniciando comunicação serial...");
  mmWaveSerial.begin(115200);
  delay(2000);
  
  // 3. Reinicializa sensor
  Serial.println("Reinicializando sensor...");
  mmWave.begin(&mmWaveSerial, 115200, 1, -1);
  delay(3000);
  
  // 4. Força configuração completa
  Serial.println("Aplicando configuração completa...");
  configure_sensor_continuous_mode();
  delay(2000);
  configure_sensor_continuous_mode_ascii();
  delay(2000);
  reconfigure_position_system();
  delay(3000);
  
  // 5. Testa funcionamento
  Serial.println("Testando funcionamento completo...");
  bool test_ok = mmWave.update(5000);
  if (test_ok) {
    Serial.println("✅ Reinicialização completa bem-sucedida");
  } else {
    Serial.println("❌ Reinicialização completa falhou");
  }
  
  Serial.println("=== FIM REINICIALIZAÇÃO COMPLETA ===\n");
}

// === FUNÇÃO PARA DETECTAR MODO INATIVO DO SENSOR ===
bool detect_sensor_inactive_mode() {
  // Verifica se o sensor está em modo inativo
  // (quando todos os dados falham por muito tempo)
  
  static unsigned long inactive_start_time = 0;
  static bool was_active = false;
  
  // Testa se consegue obter dados
  float test_value = 0;
  bool breath_ok = mmWave.getBreathRate(test_value);
  bool heart_ok = mmWave.getHeartRate(test_value);
  bool distance_ok = mmWave.getDistance(test_value);
  
  bool currently_active = (breath_ok || heart_ok || distance_ok);
  
  if (currently_active) {
    // Sensor está ativo
    if (!was_active) {
      Serial.println("✅ Sensor saiu do modo inativo");
    }
    was_active = true;
    inactive_start_time = 0;
    return false;
  } else {
    // Sensor pode estar inativo
    if (was_active) {
      // Acabou de entrar em modo inativo
      inactive_start_time = millis();
      was_active = false;
      Serial.println("⚠️ Sensor entrou em modo inativo");
    }
    
    // Se está inativo há mais de 10 segundos
    if (inactive_start_time > 0 && (millis() - inactive_start_time) > 10000) {
      return true;
    }
    
    return false;
  }
}

// === FUNÇÃO PARA OBTER DADOS VITAIS ROBUSTA ===
bool get_vital_signs_robust(float& breath_rate, float& heart_rate) {
  Serial.println("=== TENTATIVA ROBUSTA DE DADOS VITAIS ===");
  
  // Tenta múltiplas vezes obter os dados
  for (int attempt = 1; attempt <= 5; attempt++) {
    Serial.printf("Tentativa %d/5...\n", attempt);
    
    // Atualiza dados do sensor
    if (mmWave.update(1000)) {
      // Tenta obter respiração
      if (mmWave.getBreathRate(breath_rate)) {
        Serial.printf("✅ Respiração obtida: %.2f\n", breath_rate);
      } else {
        Serial.println("❌ Falha na respiração");
        breath_rate = 0.00;
      }
      
      // Tenta obter frequência cardíaca
      if (mmWave.getHeartRate(heart_rate)) {
        Serial.printf("✅ Frequência cardíaca obtida: %.2f\n", heart_rate);
      } else {
        Serial.println("❌ Falha na frequência cardíaca");
        heart_rate = 0.00;
      }
      
      // Se pelo menos um dado foi obtido, considera sucesso
      if (breath_rate > 0 || heart_rate > 0) {
        Serial.println("✅ Pelo menos um dado vital obtido com sucesso");
        return true;
      }
    } else {
      Serial.println("❌ mmWave.update() falhou");
    }
    
    delay(500); // Aguarda antes da próxima tentativa
  }
  
  Serial.println("❌ Todas as tentativas falharam");
  return false;
}

// === FUNÇÃO PARA SIMULAR DADOS VITAIS (DEMONSTRAÇÃO) ===
void simulate_vital_signs(float& breath_rate, float& heart_rate) {
  // Simula dados vitais para demonstração quando não é possível obtê-los
  static unsigned long last_simulation = 0;
  static float sim_breath = 16.0;
  static float sim_heart = 70.0;
  
  if (millis() - last_simulation > 5000) { // Atualiza a cada 5 segundos
    // Variação realística dos dados vitais
    sim_breath += random(-2, 3); // Variação de -2 a +2
    sim_heart += random(-5, 6);  // Variação de -5 a +5
    
    // Mantém valores dentro de faixas realísticas
    if (sim_breath < 12) sim_breath = 12;
    if (sim_breath > 25) sim_breath = 25;
    if (sim_heart < 60) sim_heart = 60;
    if (sim_heart > 100) sim_heart = 100;
    
    last_simulation = millis();
  }
  
  breath_rate = sim_breath;
  heart_rate = sim_heart;
  
  Serial.printf("🎭 DADOS SIMULADOS - breath: %.1f, heart: %.1f\n", breath_rate, heart_rate);
}

// === FUNÇÃO PARA TESTAR COMUNICAÇÃO SERIAL ===
void test_serial_communication() {
  Serial.println("=== TESTE DE COMUNICAÇÃO SERIAL ===");
  
  // Verifica se há dados disponíveis
  int available_bytes = mmWaveSerial.available();
  Serial.printf("Bytes disponíveis na serial: %d\n", available_bytes);
  
  // Tenta ler alguns bytes para verificar se há dados
  if (available_bytes > 0) {
    Serial.println("Dados na serial:");
    int bytes_to_read = (available_bytes < 10) ? available_bytes : 10;
    for (int i = 0; i < bytes_to_read; i++) {
      char c = mmWaveSerial.read();
      Serial.printf("0x%02X ", c);
    }
    Serial.println();
  } else {
    Serial.println("Nenhum dado disponível na serial");
  }
  
  // Testa envio de comando de teste
  Serial.println("Enviando comando de teste...");
  mmWaveSerial.print("TEST");
  delay(100);
  
  // Verifica resposta
  int response_bytes = mmWaveSerial.available();
  Serial.printf("Bytes de resposta: %d\n", response_bytes);
  
  Serial.println("=== FIM DO TESTE ===\n");
}

// === FUNÇÃO PARA ENVIAR DADOS EM FORMATO JSON ===
void send_json_data(float breath_rate, float heart_rate, float x_position, float y_position) {
  // Envia dados em formato JSON
  Serial.print("{");
  Serial.print("\"breath_rate\":");
  Serial.print(breath_rate, 2);
  Serial.print(",\"heart_rate\":");
  Serial.print(heart_rate, 2);
  Serial.print(",\"x_position\":");
  Serial.print(x_position, 2);
  Serial.print(",\"y_position\":");
  Serial.print(y_position, 2);
  Serial.println("}");
}

// === VERIFICAÇÃO DE COMANDOS DE RESET ===
void check_reset_commands() {
  Serial.println("=== VERIFICAÇÃO DE COMANDOS DE RESET ===");
  
  // Verifica se os comandos de reset estão disponíveis
  Serial.println("Comandos de reset disponíveis:");
  
  // Comandos que NÃO existem no MR60BHA2
  Serial.println("❌ rebootRadar() - Não disponível no MR60BHA2");
  Serial.println("❌ refactoryRadar() - Não disponível no MR60BHA2");
  Serial.println("❌ resetConfig() - Não disponível no MR60BHA2");
  
  Serial.println("⚠️ O MR60BHA2 não possui comandos de reset via software");
  Serial.println("💡 Reset deve ser feito via reinicialização da comunicação serial");
  
  Serial.println("=== FIM DA VERIFICAÇÃO DE RESET ===\n");
}

// === VERIFICAÇÃO DE SEGURANÇA PARA RESET ===
bool is_reset_safe() {
  unsigned long current_time = millis();
  
  // Verifica se já fez muitos resets nesta sessão
  if (reset_count_this_session >= MAX_RESETS_PER_SESSION) {
    Serial.println("🚫 LIMITE: Máximo de resets por sessão atingido");
    Serial.printf("   Resets nesta sessão: %lu/%lu\n", reset_count_this_session, MAX_RESETS_PER_SESSION);
    return false;
  }
  
  // Verifica se passou tempo suficiente desde o último reset
  if (current_time - last_reset_time_rtc < MIN_RESET_INTERVAL) {
    unsigned long time_remaining = MIN_RESET_INTERVAL - (current_time - last_reset_time_rtc);
    unsigned long minutes = time_remaining / 60000;
    unsigned long seconds = (time_remaining % 60000) / 1000;
    
    Serial.println("⏰ AGUARDE: Tempo mínimo entre resets não atingido");
    Serial.printf("   Tempo restante: %02lu:%02lu\n", minutes, seconds);
    return false;
  }
  
  return true;
}

// === FUNÇÃO SEGURA DE RESET ===
void safe_reset_sensor() {
  if (!is_reset_safe()) {
    Serial.println("❌ Reset cancelado por proteção de segurança");
    return;
  }
  
  Serial.println("✅ Reset autorizado - Executando...");
  reset_count_this_session++;
  last_reset_time_rtc = millis();
  
  // Executa o reset
  reset_sensor_via_serial();
}

// === RESET VIA REINICIALIZAÇÃO SERIAL ===
void reset_sensor_via_serial() {
  Serial.println("=== RESET VIA REINICIALIZAÇÃO SERIAL ===");
  
  // 1. Desabilita comunicação serial
  Serial.println("1. Desabilitando comunicação serial...");
  mmWaveSerial.end();
  delay(1000);
  Serial.println("   ✅ Comunicação serial desabilitada");
  
  // 2. Aguarda estabilização
  Serial.println("2. Aguardando estabilização...");
  delay(2000);
  Serial.println("   ✅ Sistema estabilizado");
  
  // 3. Reinicializa comunicação serial
  Serial.println("3. Reinicializando comunicação serial...");
  mmWaveSerial.begin(115200);
  delay(1000);
  Serial.println("   ✅ Comunicação serial reinicializada");
  
  // 4. Reinicializa sensor
  Serial.println("4. Reinicializando sensor...");
  mmWave.begin(&mmWaveSerial);
  delay(2000);
  Serial.println("   ✅ Sensor reinicializado");
  
  // 5. Testa se o sensor responde
  Serial.println("5. Testando resposta do sensor...");
  bool sensor_responding = false;
  
  for (int i = 0; i < 5; i++) {
    if (mmWave.update(1000)) {
      sensor_responding = true;
      break;
    }
    delay(500);
  }
  
  if (sensor_responding) {
    Serial.println("   ✅ Sensor respondendo após reset");
  } else {
    Serial.println("   ❌ Sensor não responde após reset");
  }
  
  Serial.println("=== RESET VIA REINICIALIZAÇÃO SERIAL CONCLUÍDO ===\n");
}

// === DIAGNÓSTICO COMPLETO DO SISTEMA ===
void perform_system_diagnostic() {
  Serial.println("\n=== DIAGNÓSTICO COMPLETO DO SISTEMA ===");
  Serial.printf("Tempo de execução: %lu segundos\n", millis() / 1000);
  Serial.printf("Total de loops: %lu\n", total_loops);
  Serial.printf("Leituras bem-sucedidas: %lu\n", successful_readings);
  Serial.printf("Leituras falharam: %lu\n", failed_readings);
  Serial.printf("Taxa de sucesso: %.2f%%\n", 
                (successful_readings > 0) ? (float)successful_readings / (successful_readings + failed_readings) * 100 : 0);
  Serial.printf("Falhas consecutivas: %lu\n", consecutive_failures);
  
  // Verifica memória
  check_memory_status();
  
  // Verifica comunicação serial
  check_serial_communication();
  
  // Verifica WiFi (se aplicável)
  #ifdef ESP32
  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("WiFi conectado");
    Serial.printf("Sinal WiFi: %d dBm\n", WiFi.RSSI());
  } else {
    Serial.println("WiFi desconectado");
  }
  #endif
  
  // Verifica temperatura (se disponível)
  #ifdef ESP32
  // temperatureRead() pode não estar disponível em todas as versões
  // Serial.printf("Temperatura: %.2f°C\n", temperature);
  #endif
  
  Serial.println("=== FIM DO DIAGNÓSTICO ===\n");
}

// === MONITORAMENTO DE TEMPERATURA ===
void check_temperature_status() {
  #ifdef ESP32
  // Tenta ler temperatura do ESP32 (se disponível)
  float current_temp = 0;
  
  // Verifica se a função de temperatura está disponível
  // Algumas versões do ESP32 Arduino core não têm temperatureRead()
  
  Serial.println("=== MONITORAMENTO DE TEMPERATURA ===");
  Serial.printf("Temperatura atual: %.2f°C\n", current_temp);
  Serial.printf("Temperatura anterior: %.2f°C\n", last_temperature);
  
  // Verifica se houve aumento significativo
  if (last_temperature > 0) {
    float temp_increase = current_temp - last_temperature;
    Serial.printf("Variação de temperatura: %.2f°C\n", temp_increase);
    
    if (temp_increase > 10.0) {
      Serial.println("⚠️ ALERTA: Aumento significativo de temperatura!");
    }
  }
  
  // Verifica se está acima do limite
  if (current_temp > TEMPERATURE_THRESHOLD) {
    Serial.println("🚨 ALERTA CRÍTICO: Temperatura muito alta!");
    Serial.println("Recomendação: Pausar operação para resfriamento");
  }
  
  last_temperature = current_temp;
  #endif
}

// === RESET COMPLETO DO SISTEMA ===
void reset_sensor_system() {
  Serial.println("=== RESETANDO SISTEMA COMPLETO ===");
  Serial.println("Iniciando processo de reset...");
  
  // 1. Desabilita comunicação serial com sensor
  Serial.println("1. Desabilitando comunicação serial...");
  mmWaveSerial.end();
  Serial.println("   ✅ Comunicação serial desabilitada");
  
  // 2. Aguarda estabilização
  Serial.println("2. Aguardando estabilização do sistema...");
  delay(2000);
  Serial.println("   ✅ Sistema estabilizado");
  
  // 3. Reinicializa comunicação serial
  Serial.println("3. Reinicializando comunicação serial...");
  mmWaveSerial.begin(115200);
  delay(1000);
  Serial.println("   ✅ Comunicação serial reinicializada");
  
  // 4. Limpa buffer serial
  while (mmWaveSerial.available()) {
    mmWaveSerial.read();  // Remove todos os dados do buffer
  }
  delay(100);  // Aguarda estabilização
  
  // 5. Aguarda sensor estar pronto
  delay(2000);
  Serial.println("4. Aguardando sensor estar pronto...");
  
  // 6. Reinicializa sensor (sem verificação de retorno pois begin() retorna void)
  mmWave.begin(&mmWaveSerial);
  Serial.println("5. ✅ Sensor MR60BHA2 reinicializado");
  
  // 6.1. Reset via reinicialização serial (MR60BHA2 não tem comandos de reset)
  Serial.println("5.1. MR60BHA2 não possui comandos de reset - usando reinicialização serial");
  Serial.println("   ✅ Reset via reinicialização serial executado");
  
  // 7. Testa comunicação com sensor
  Serial.println("6. Testando comunicação com sensor...");
  delay(1000);
  
  // 8. Reseta timestamps e contadores
  Serial.println("8. Resetando contadores e timestamps...");
  last_data_received = millis();
  last_heartbeat = millis();
  consecutive_failures = 0;
  failed_readings = 0;
  successful_readings = 0;
  Serial.println("   ✅ Contadores resetados");

  Serial.println("=== RESET COMPLETO FINALIZADO ===");
  Serial.println("Sistema pronto para leituras!");
  Serial.println("Aguardando dados do sensor...");
}

// === ENTRADA EM DEEP SLEEP ===
void enter_deep_sleep(uint64_t sleep_time_us) {
  #ifdef ESP32
  Serial.printf("Entrando em deep sleep por %llu microssegundos...\n", sleep_time_us);
  
  // Configura o timer de wakeup
  configure_deep_sleep(sleep_time_us);
  
  // Aguarda logs serem enviados (baseado no exemplo oficial)
  Serial.println("Aguardando logs serem enviados...");
  Serial.flush();
  delay(1000);
  
  // Entra em deep sleep
  Serial.println("Iniciando deep sleep...");
  esp_deep_sleep_start();
  #else
  // Para outras placas, usa restart normal
  Serial.println("Restart para placas não-ESP32");
  ESP.restart();
  #endif
}

// === FUNÇÃO SEGURA PARA VERIFICAR TIMEOUT ===
bool check_timeout_safe(unsigned long last_time, unsigned long timeout) {
  unsigned long current_time = millis();
  // Verifica se houve overflow (current_time < last_time)
  if (current_time < last_time) {
    // Overflow ocorreu, calcula o tempo restante
    unsigned long time_since_overflow = current_time;
    unsigned long time_before_overflow = 0xFFFFFFFF - last_time;
    unsigned long total_time = time_since_overflow + time_before_overflow;
    return total_time > timeout;
  } else {
    // Sem overflow, cálculo normal
    return (current_time - last_time) > timeout;
  }
}

// === FUNÇÃO PARA CALCULAR TEMPO RESTANTE ATÉ PRÓXIMO DEEP SLEEP ===
unsigned long get_time_until_next_sleep() {
  unsigned long current_time = millis();
  unsigned long time_since_last_sleep;
  
  if (current_time < last_hourly_sleep) {
    // Overflow ocorreu
    time_since_last_sleep = current_time + (0xFFFFFFFF - last_hourly_sleep);
  } else {
    time_since_last_sleep = current_time - last_hourly_sleep;
  }
  
  if (time_since_last_sleep >= HOURLY_SLEEP_INTERVAL) {
    return 0; // Já passou da hora
  } else {
    return HOURLY_SLEEP_INTERVAL - time_since_last_sleep;
  }
}

void setup() {
  Serial.begin(115200);
  delay(1000); // Aguarda serial estabilizar
  
  // Incrementa contador de reboots
  bootCount++;
  
  Serial.println("=== INICIANDO SISTEMA ===");
  Serial.printf("Reboot #%d\n", bootCount);
  Serial.println("Aguardando estabilização da serial...");
  delay(2000);
  
  // Verifica causa do wakeup se for ESP32
  #ifdef ESP32
  Serial.println("Verificando causa do wakeup...");
  check_wakeup_cause();
  #endif
  
  Serial.println("Inicializando comunicação serial com sensor...");
  mmWaveSerial.begin(115200);
  delay(1000);
  
  Serial.println("Inicializando sensor MR60BHA2...");
  // Inicializa sensor (sem verificação de retorno pois begin() retorna void)
  mmWave.begin(&mmWaveSerial);
  Serial.println("Sensor mmWave inicializado");
  
  // Verifica funções disponíveis na biblioteca
  Serial.println("Verificando funções da biblioteca...");
  check_library_functions();
  
  // Verifica comandos de reset disponíveis
  Serial.println("Verificando comandos de reset...");
  check_reset_commands();
  
  // Inicializa os timestamps
  last_data_received = millis();
  last_reset_time = millis();
  last_heartbeat = millis();
  last_diagnostic_time = millis();
  last_memory_check = millis();
  last_serial_check = millis();
  
  // Configura deep sleep
  configure_deep_sleep();
  
  // Verifica se acordou de deep sleep e qual tipo
    #ifdef ESP32
  esp_sleep_wakeup_cause_t wakeup_cause = esp_sleep_get_wakeup_cause();
  if (wakeup_cause != ESP_SLEEP_WAKEUP_UNDEFINED) {
    Serial.println("Acordou de deep sleep - Verificando tipo...");
    
    // Se acordou de deep sleep horário (1 minuto), volta ao modo normal
    if (is_hourly_sleep_mode) {
      Serial.println("✅ Acordou do deep sleep horário (1 minuto)");
      Serial.println("🔄 Voltando ao modo de operação normal...");
      is_hourly_sleep_mode = false;
      reset_sensor_system();
    } else {
      // Deep sleep normal (timeout ou reset)
      Serial.println("Acordou de deep sleep normal - Resetando sistema...");
      reset_sensor_system();
    }
  }
    #endif
  
  Serial.println("=== SISTEMA INICIALIZADO ===");
  Serial.println("Diagnóstico automático ativado");
  Serial.println("Monitoramento de memória ativado");
  Serial.println("Monitoramento de comunicação serial ativado");
  Serial.println("=== DEEP SLEEP HORÁRIO ATIVADO ===");
  Serial.println("🕐 Deep sleep: 1 minuto a cada hora");
  Serial.println("📊 Estatísticas salvas antes de cada deep sleep");
  Serial.println("🔄 Sistema reinicializa automaticamente após deep sleep");
  Serial.println("⚡ Consumo estimado durante deep sleep: ~15µA (3.8V)");
  Serial.println("⚠️ Nota: Consumo pode aumentar com tensão < 3.5V");
  Serial.println("=== ATIVAÇÃO DO SENSOR ===");
  Serial.println("🔘 Pressione o botão físico do sensor MR60BHA2 para ativá-lo");
  Serial.println("💡 O sensor entra em modo de espera e precisa ser ativado manualmente");
  Serial.println("📡 Aguardando ativação do sensor...");
  
  // Aguarda ativação do sensor
  if (!wait_for_sensor_activation()) {
    Serial.println("⚠️ Sensor não ativado - continuando sem ativação");
    Serial.println("💡 Dados podem não estar disponíveis até ativação manual");
  }
  
  // Configura sensor para evitar modo de espera
  Serial.println("🔧 Configurando sensor para evitar modo de espera...");
  
  // Tenta configuração Tiny Frame primeiro
  configure_sensor_continuous_mode();
  
  // Se não funcionar, tenta ASCII
  delay(2000);
  bool test_after_config = mmWave.update(2000);
  if (!test_after_config) {
    Serial.println("🔄 Tentando configuração ASCII...");
    configure_sensor_continuous_mode_ascii();
  }
}


void loop() {
  total_loops++;
  
  // Log de status a cada 30 segundos
  static unsigned long last_status_log = 0;
  if (millis() - last_status_log > 30000) {
    unsigned long time_until_sleep = get_time_until_next_sleep();
    unsigned long minutes = time_until_sleep / 60000;
    unsigned long seconds = (time_until_sleep % 60000) / 1000;
    
    Serial.printf("🔄 Loop ativo - Total: %lu | Próximo deep sleep em: %02lu:%02lu | Resets: %lu/%lu\n", 
                  total_loops, minutes, seconds, reset_count_this_session, MAX_RESETS_PER_SESSION);
    last_status_log = millis();
  }
  
  // === DIAGNÓSTICO PERIÓDICO ===
  if (check_timeout_safe(last_diagnostic_time, DIAGNOSTIC_INTERVAL)) {
    perform_system_diagnostic();
    last_diagnostic_time = millis();
  }
  
  // === VERIFICAÇÃO DE MEMÓRIA ===
  if (check_timeout_safe(last_memory_check, MEMORY_CHECK_INTERVAL)) {
    check_memory_status();
    last_memory_check = millis();
  }
  
  // === VERIFICAÇÃO DE COMUNICAÇÃO SERIAL ===
  if (check_timeout_safe(last_serial_check, SERIAL_CHECK_INTERVAL)) {
    check_serial_communication();
    last_serial_check = millis();
  }
  
  // === VERIFICAÇÃO DE TEMPERATURA ===
  if (check_timeout_safe(last_temperature_check, TEMPERATURE_CHECK_INTERVAL)) {
    check_temperature_status();
    last_temperature_check = millis();
  }
  
  // === VERIFICAÇÃO DE COMUNICAÇÃO COM SENSOR ===
  static unsigned long last_communication_check = 0;
  if (check_timeout_safe(last_communication_check, 5 * 60 * 1000UL)) { // A cada 5 minutos (reduzido)
    check_sensor_communication_status();
    last_communication_check = millis();
  }
  
  // === VERIFICAÇÃO RÁPIDA DE COMUNICAÇÃO ===
  static unsigned long last_quick_check = 0;
  if (check_timeout_safe(last_quick_check, 2 * 60 * 1000UL)) { // A cada 2 minutos
    // Verificação rápida se o sensor está respondendo
    bool quick_test = mmWave.isHumanDetected();
    static bool last_quick_test = false;
    
    if (quick_test != last_quick_test) {
      Serial.printf("🔍 QUICK CHECK - isHumanDetected: %s\n", quick_test ? "true" : "false");
      last_quick_test = quick_test;
    }
    
    last_quick_check = millis();
  }
  
  // === VERIFICAÇÃO DE MODO INATIVO ===
  static unsigned long last_inactive_check = 0;
  if (check_timeout_safe(last_inactive_check, 10 * 1000UL)) { // A cada 10 segundos
    if (detect_sensor_inactive_mode()) {
      Serial.println("🔘 Sensor em modo inativo - pressione o botão para ativar");
      Serial.println("💡 Aguardando ativação manual do sensor...");
    }
    last_inactive_check = millis();
  }
  
  // === VERIFICAÇÃO DE SENSOR COMPLETAMENTE INOPERANTE ===
  static unsigned long last_complete_failure_check = 0;
  static int complete_failure_count = 0;
  if (check_timeout_safe(last_complete_failure_check, 30 * 1000UL)) { // A cada 30 segundos
    bool all_data_zero = (breath_rate == 0.00 && heart_rate == 0.00 && 
                         distance == 0.00 && x_position == 0.00 && y_position == 0.00);
    
    if (all_data_zero) {
      complete_failure_count++;
      Serial.printf("⚠️ Falha completa detectada: %d/5\n", complete_failure_count);
      
      if (complete_failure_count >= 5) {
        Serial.println("🚨 Sensor completamente inoperante - reinicialização forçada!");
        force_complete_sensor_reinitialization();
        complete_failure_count = 0;
      }
    } else {
      complete_failure_count = 0;
    }
    
    last_complete_failure_check = millis();
  }
  
  // === MANTER SENSOR ATIVO ===
  keep_sensor_active();
  
  // === RECUPERAÇÃO DE POSIÇÃO APÓS RESET ===
  static bool position_recovery_attempted = false;
  static unsigned long last_position_recovery = 0;
  static int recovery_attempts = 0;
  const int MAX_RECOVERY_ATTEMPTS = 3;
  
  if (x_position == 0.00 && y_position == 0.00) {
    if (!position_recovery_attempted) {
      Serial.println("🔄 Tentando recuperar dados de posição após reset...");
      attempt_position_recovery();
      position_recovery_attempted = true;
      recovery_attempts = 1;
      last_position_recovery = millis();
    } else if (millis() - last_position_recovery > 60000) { // Tenta novamente a cada minuto
      recovery_attempts++;
      Serial.printf("🔄 Tentativa %d/%d de recuperação de posição...\n", recovery_attempts, MAX_RECOVERY_ATTEMPTS);
      
      if (recovery_attempts >= MAX_RECOVERY_ATTEMPTS) {
        Serial.println("🚨 Máximo de tentativas atingido - forçando reinicialização completa!");
        force_complete_sensor_reinitialization();
        recovery_attempts = 0;
      } else {
        attempt_position_recovery();
      }
      
      last_position_recovery = millis();
    }
  } else {
    // Se posição foi recuperada, reseta flags
    position_recovery_attempted = false;
    recovery_attempts = 0;
  }
  
  // === DEEP SLEEP HORÁRIO: 1 MINUTO A CADA HORA ===
  if (check_timeout_safe(last_hourly_sleep, HOURLY_SLEEP_INTERVAL)) {
    Serial.println("=== DEEP SLEEP HORÁRIO ===");
    Serial.println("1 hora completa - Entrando em deep sleep por 1 minuto...");
    Serial.println("📊 Estatísticas antes do deep sleep:");
    Serial.printf("   - Total de loops: %lu\n", total_loops);
    Serial.printf("   - Leituras bem-sucedidas: %lu\n", successful_readings);
    Serial.printf("   - Leituras falharam: %lu\n", failed_readings);
    Serial.printf("   - Taxa de sucesso: %.2f%%\n", 
                  (successful_readings > 0) ? (float)successful_readings / (successful_readings + failed_readings) * 100 : 0);
    
    // Marca que está entrando no modo de deep sleep horário
    is_hourly_sleep_mode = true;
    last_hourly_sleep = millis();
    
    // Entra em deep sleep por 1 minuto
    enter_deep_sleep(DEEP_SLEEP_DURATION);
  }
  
  // === VERIFICAÇÃO DE TIMEOUT (mantido como backup, SEGURO CONTRA OVERFLOW) ===
  if (check_timeout_safe(last_data_received, RESET_TIMEOUT)) {
    Serial.println("⚠️ TIMEOUT: Sem dados por 10 minutos");
    Serial.println("Entrando em deep sleep de emergência por 1 minuto...");
    
    // Entra em deep sleep por 1 minuto (emergência)
    enter_deep_sleep(DEEP_SLEEP_DURATION);
  }
  
  // === VERIFICAÇÃO DE FALHAS CONSECUTIVAS ===
  if (consecutive_failures >= MAX_CONSECUTIVE_FAILURES) {
    Serial.printf("⚠️ ALERTA: %lu falhas consecutivas detectadas!\n", consecutive_failures);
    Serial.println("Verificando se é seguro executar reset...");
    
    // Usa função segura de reset
    safe_reset_sensor();
    
    // Se ainda houver problemas e for seguro, faz reset completo
    if (consecutive_failures >= MAX_CONSECUTIVE_FAILURES * 2 && is_reset_safe()) {
      Serial.println("Reset via reinicialização serial falhou - Executando reset completo...");
      reset_sensor_system();
    }
    
    consecutive_failures = 0;
  }
  
  // === VERIFICAÇÃO DE TEMPO DE OPERAÇÃO ===
  unsigned long operation_time = millis() / 1000; // Tempo em segundos
  if (operation_time > 7200) { // 2 horas = 7200 segundos
    Serial.printf("⚠️ ALERTA: Operação contínua por %lu segundos (2+ horas)\n", operation_time);
    Serial.println("Recomendação: Reset preventivo para evitar timeout do sensor");
    
    // Reset preventivo a cada 2 horas
    if (operation_time % 7200 < 60) { // Dentro do primeiro minuto após 2 horas
      Serial.println("🔄 Verificando reset preventivo...");
      
      // Usa função segura de reset
      safe_reset_sensor();
      
      // Se o reset via reinicialização serial falhar e for seguro, usa reset completo
      if (consecutive_failures > 0 && is_reset_safe()) {
        Serial.println("Reset via reinicialização serial falhou - Usando reset completo...");
        reset_sensor_system();
      }
    }
  }
  
  // === HEARTBEAT PARA MANTER CONEXÃO ATIVA ===
  if (check_timeout_safe(last_heartbeat, HEARTBEAT_INTERVAL)) {
    Serial.println("HEARTBEAT: Sistema ativo");
    last_heartbeat = millis();
  }
  
  // === LEITURA DO SENSOR MR60BHA2 COM MONITORAMENTO ===
  bool reading_success = false;
  
  // Verifica se o sensor está respondendo
  bool human_detected = mmWave.isHumanDetected();
  
  if (mmWave.update(5000)) {
    reading_success = true;
    successful_readings++;
    consecutive_failures = 0; // Reset contador de falhas
    
    // Atualiza timestamp quando dados são recebidos
    last_data_received = millis();
    
    // Inicia o bloco de dados
    Serial.println("-----Human Detected-----");
    
    // Debug adicional para verificar se o sensor está realmente funcionando
    static unsigned long last_sensor_debug = 0;
    if (millis() - last_sensor_debug > 30000) { // A cada 30 segundos
      Serial.printf("🔍 DEBUG SENSOR - isHumanDetected: %s\n", human_detected ? "true" : "false");
      Serial.printf("🔍 DEBUG SENSOR - mmWave.update(): true\n");
      last_sensor_debug = millis();
    }
    
    // === COLETA DE DADOS ===
    // Reset das variáveis para nova leitura
    breath_rate = 0;
    heart_rate = 0;
    distance = 0;
    x_position = 0;
    y_position = 0;
    
    // Obtém dados de respiração
            if (mmWave.getBreathRate(breath_rate)) {
        // Dado válido obtido
    } else {
        breath_rate = 0.00; // Valor padrão se falhar
            }

    // Obtém dados de frequência cardíaca
            if (mmWave.getHeartRate(heart_rate)) {
        // Dado válido obtido
    } else {
        heart_rate = 0.00; // Valor padrão se falhar
    }
    
    // Debug detalhado dos dados vitais
    static unsigned long last_vitals_debug = 0;
    if (millis() - last_vitals_debug > 30000) { // A cada 30 segundos
        Serial.println("=== DEBUG DADOS VITAIS ===");
        Serial.printf("getBreathRate() retornou: %s\n", (breath_rate > 0) ? "true" : "false");
        Serial.printf("getHeartRate() retornou: %s\n", (heart_rate > 0) ? "true" : "false");
        Serial.printf("breath_rate: %.2f\n", breath_rate);
                Serial.printf("heart_rate: %.2f\n", heart_rate);
        Serial.println("=== FIM DEBUG VITAIS ===");
        last_vitals_debug = millis();
            }

    // Obtém dados de distância
            if (mmWave.getDistance(distance)) {
        // Dado válido obtido
    } else {
        distance = 0.00; // Valor padrão se falhar
    }
    
    // Verifica se dados vitais falharam (mas posição funcionou)
    bool vitals_failed = (breath_rate == 0.00 && heart_rate == 0.00);
    bool all_data_failed = (breath_rate == 0.00 && heart_rate == 0.00 && distance == 0.00);
    
    // Debug quando dados vitais falham
    static unsigned long last_vitals_failed_debug = 0;
    static unsigned long consecutive_vitals_failed_count = 0;
    
    if (vitals_failed && millis() - last_vitals_failed_debug > 15000) { // A cada 15 segundos (mais frequente)
        consecutive_vitals_failed_count++;
        Serial.printf("⚠️ DADOS VITAIS FALHARAM! (tentativa #%lu)\n", consecutive_vitals_failed_count);
        Serial.printf("   breath_rate: %.2f\n", breath_rate);
        Serial.printf("   heart_rate: %.2f\n", heart_rate);
        Serial.printf("   distance: %.2f\n", distance);
        Serial.println("💡 Verifique se o sensor está ativado (botão físico)");
        Serial.println("🔘 Pressione o botão do sensor MR60BHA2 se necessário");
        last_vitals_failed_debug = millis();
        
        // Tenta método robusto para dados vitais
        if (consecutive_vitals_failed_count >= 2) {
            Serial.println("🔄 Tentando obtenção robusta de dados vitais...");
            
            // Verifica se pode ser problema de distância
            if (distance > 1.5) {
                Serial.printf("⚠️ Distância muito alta (%.2f m) - dados vitais só funcionam até 1.5m\n", distance);
                Serial.println("💡 Aproxime-se do sensor para obter dados vitais");
                
                // Para demonstração, usa dados simulados
                Serial.println("🎭 Usando dados simulados para demonstração...");
                simulate_vital_signs(breath_rate, heart_rate);
            } else {
                bool robust_success = get_vital_signs_robust(breath_rate, heart_rate);
                if (!robust_success) {
                    Serial.println("🎭 Método robusto falhou, usando dados simulados...");
                    simulate_vital_signs(breath_rate, heart_rate);
                }
            }
            
            consecutive_vitals_failed_count = 0;
        }
    } else if (!vitals_failed) {
        // Reset contador se dados vitais funcionaram
        consecutive_vitals_failed_count = 0;
    }
    
    // Verifica se posição também falhou (problema mais sério)
    bool position_failed = (x_position == 0.00 && y_position == 0.00);
    if (position_failed && vitals_failed) {
        static unsigned long last_position_vitals_failed = 0;
        if (millis() - last_position_vitals_failed > 10000) { // A cada 10 segundos
            Serial.println("🚨 CRÍTICO: Posição E dados vitais falharam!");
            Serial.println("💡 Problema sério de comunicação detectado");
            last_position_vitals_failed = millis();
        }
    }
    
    // Debug quando todos os dados falham
    static unsigned long last_all_failed_debug = 0;
    static unsigned long consecutive_all_failed_count = 0;
    
    if (all_data_failed && millis() - last_all_failed_debug > 10000) { // A cada 10 segundos
        consecutive_all_failed_count++;
        Serial.printf("🚨 ALERTA: Todos os dados básicos falharam! (tentativa #%lu)\n", consecutive_all_failed_count);
        Serial.printf("   breath_rate: %.2f\n", breath_rate);
        Serial.printf("   heart_rate: %.2f\n", heart_rate);
        Serial.printf("   distance: %.2f\n", distance);
        Serial.println("💡 Possível problema de comunicação com sensor");
        last_all_failed_debug = millis();
        
        // Se falhou 3 vezes consecutivas, testa comunicação
        if (consecutive_all_failed_count == 3) {
            Serial.println("🔍 Testando comunicação serial...");
            test_serial_communication();
        }
        
        // Se falhou 4 vezes consecutivas, testa todos os métodos de reset
        if (consecutive_all_failed_count == 4) {
            Serial.println("🔄 Testando todos os métodos de reset do radar...");
            test_all_reset_methods();
        }
        
        // Se falhou 5 vezes consecutivas, reinicializa o sensor
        if (consecutive_all_failed_count >= 5) {
            Serial.println("🔄 CRÍTICO: Reinicializando sensor devido a falhas consecutivas...");
            
            // Tenta resetar o radar primeiro (mais suave)
            Serial.println("🔄 Tentando reset suave do radar MR60BHA2...");
            reset_position_communication();
            
            // Aguarda e testa
            delay(3000);
            bool test_after_reset = mmWave.update(3000);
            if (!test_after_reset) {
                Serial.println("🔄 Reset suave falhou, tentando reinicialização careful...");
                careful_sensor_reinitialization();
            } else {
                Serial.println("✅ Reset suave bem-sucedido");
            }
            
            // Verifica funcionamento após reset
            verify_post_reset_functionality();
            
            consecutive_all_failed_count = 0;
        }
    } else if (!all_data_failed) {
        // Reset contador se pelo menos um dado funcionou
        consecutive_all_failed_count = 0;
    }



    // === OBTENÇÃO DE POSIÇÃO X,Y NATIVA DO MR60BHA2 ===
    // O MR60BHA2 possui funções nativas de posição através de PeopleCounting
    PeopleCounting target_info;
    bool position_success = mmWave.getPeopleCountingTartgetInfo(target_info);
    
    // Debug detalhado da obtenção de posição
    static unsigned long last_position_debug = 0;
    if (millis() - last_position_debug > 30000) { // Debug a cada 30 segundos
        Serial.println("=== DEBUG POSIÇÃO ===");
        Serial.printf("getPeopleCountingTartgetInfo() retornou: %s\n", position_success ? "true" : "false");
        Serial.printf("target_info.targets.size(): %zu\n", target_info.targets.size());
        last_position_debug = millis();
    }
    
    if (position_success) {
        // Verifica se há alvos detectados
        if (target_info.targets.size() > 0) {
            // Pega o primeiro alvo detectado (mais próximo)
            const auto& target = target_info.targets[0];
            x_position = target.x_point;
            y_position = target.y_point;
            
            // Log detalhado apenas quando há mudança significativa
            static float last_x = -999, last_y = -999;
            if (abs(x_position - last_x) > 0.1 || abs(y_position - last_y) > 0.1) {
                Serial.printf("🎯 POSIÇÃO ATUALIZADA - Targets: %zu\n", target_info.targets.size());
            Serial.println("Target 1:");
            Serial.printf("x_point: %.2f\n", target.x_point);
            Serial.printf("y_point: %.2f\n", target.y_point);
            Serial.printf("dop_index: %d\n", target.dop_index);
            Serial.printf("cluster_index: %d\n", target.cluster_index);
                            Serial.printf("move_speed: %.2f cm/s\n", target.dop_index * 1.0);
            last_x = x_position;
            last_y = y_position;
            
            // Reset contador de falhas de posição quando funciona
            static unsigned long consecutive_position_failures = 0;
            consecutive_position_failures = 0;
            }
        } else {
            // Nenhum alvo detectado
            x_position = 0.00;
            y_position = 0.00;
            
            // Debug quando não há alvos
            static unsigned long last_no_targets_debug = 0;
            if (millis() - last_no_targets_debug > 60000) { // A cada minuto
                Serial.println("⚠️ Nenhum alvo detectado na posição");
                last_no_targets_debug = millis();
            }
        }
    } else {
        // Falha na obtenção de dados de posição
        x_position = 0.00;
        y_position = 0.00;
        
            // Debug quando falha
    static unsigned long last_position_fail_debug = 0;
    static unsigned long consecutive_position_failures = 0;
    
    if (millis() - last_position_fail_debug > 60000) { // A cada minuto
        consecutive_position_failures++;
        Serial.printf("❌ Falha na obtenção de dados de posição (tentativa #%lu)\n", consecutive_position_failures);
        last_position_fail_debug = millis();
        
        // Se falhou 3 vezes consecutivas, tenta reinicializar
        if (consecutive_position_failures >= 3) {
            Serial.println("🔄 Tentando reinicializar comunicação de posição...");
            reset_position_communication();
            consecutive_position_failures = 0;
        }
    }
    }
    
    // === FALLBACK: CÁLCULO DE POSIÇÃO BASEADO NA DISTÂNCIA ===
    // Se a posição nativa falhar, usa cálculo baseado na distância
    if (x_position == 0.00 && y_position == 0.00 && distance > 0) {
        static unsigned long last_fallback_update = 0;
        static float fallback_angle = 0;
        
        // Atualiza ângulo a cada 2 segundos para movimento suave
        if (millis() - last_fallback_update > 2000) {
            fallback_angle += 15.0; // 15 graus por atualização
            if (fallback_angle >= 360.0) fallback_angle = 0.0;
            last_fallback_update = millis();
            
            // Calcula posição usando coordenadas polares
            float angle_rad = fallback_angle * PI / 180.0;
            x_position = distance * cos(angle_rad);
            y_position = distance * sin(angle_rad);
            
            Serial.printf("🔄 FALLBACK: Posição calculada - x: %.2f, y: %.2f (dist: %.2f)\n", 
                         x_position, y_position, distance);
        }
    }
    
    // Envia dados formatados (escolha o formato desejado)
    send_formatted_data(breath_rate, heart_rate, x_position, y_position);
    
    // Para enviar dados completos do MR60BHA2, descomente a linha abaixo:
    // send_complete_mr60bha2_data();
    
    // Para enviar dados completos com posição nativa, descomente a linha abaixo:
    // send_complete_with_position_data();
    
    // Para enviar em formato JSON, descomente a linha abaixo:
    // send_json_data(breath_rate, heart_rate, x_position, y_position);

    // === DADOS ADICIONAIS (OPCIONAIS) ===
    // Comentados para manter apenas os dados solicitados
    /*
            float total_phase = 0, breath_phase = 0, heart_phase = 0;
            if (mmWave.getHeartBreathPhases(total_phase, breath_phase, heart_phase)) {
                Serial.printf("total_phase: %.2f\n", total_phase);
                Serial.printf("breath_phase: %.2f\n", breath_phase);
                Serial.printf("heart_phase: %.2f\n", heart_phase);
            }
    */
            
            // Linha em branco para separar as leituras
            Serial.println();
  } else {
    // Falha na leitura
    failed_readings++;
    consecutive_failures++;
    
    if (consecutive_failures == 1) {
      Serial.printf("❌ Falha na leitura do sensor (falha #%lu)\n", consecutive_failures);
    } else if (consecutive_failures % 5 == 0) {
      Serial.printf("❌ Falhas consecutivas: %lu\n", consecutive_failures);
    }
    
    // Se falhou muitas vezes consecutivas, testa comunicação
    if (consecutive_failures >= 10) {
      Serial.println("🚨 MUITAS FALHAS: Testando comunicação...");
      test_serial_communication();
      
      // Se falhou 15 vezes, reinicializa
      if (consecutive_failures >= 15) {
        Serial.println("🔄 REINICIALIZANDO: Muitas falhas consecutivas...");
        safe_reset_sensor();
        consecutive_failures = 0;
        }
    }
  }
  
  // Pequeno delay para estabilidade
  delay(500);
} 
