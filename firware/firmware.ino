#include <Wire.h>
#include <LiquidCrystal_I2C.h>
#include <Adafruit_Sensor.h>
#include <Adafruit_BME280.h>
#include <Adafruit_MAX44009.h>
#include <ESP8266WiFi.h>
#include <ESP8266WebServer.h>
#include <WiFiClientSecure.h>

#define BTN_UP_PIN 12
#define BTN_OK_PIN 13
#define POT_PIN A0

#define LCD_ADDR 0x27
#define BME_ADDR 0x76

#define STATION_SERIAL "ESP8266_001" // ESP_id

const char* ssid = "WifiName";
const char* password = "password";

#define BOT_TOKEN "8640880793:AAG9DBZakOf216gYBetvtyDga65dktvczww"
#define CHAT_ID "-5040780949"
#define SEND_INTERVAL 60000 

unsigned long lastSend = 0;

ESP8266WebServer server(80);

LiquidCrystal_I2C lcd(LCD_ADDR, 16, 2);
Adafruit_BME280 bme;
Adafruit_MAX44009 max44009;

float t = 0;
float h = 0;
float p = 0;
float lux = 0;

bool bmeOk = false;
bool lightOk = false;

String lastWebStatus = "Нет ручной отправки";
unsigned long lastWebSendTime = 0;

int menuIndex = 0;
int menuItemCount = 5;
bool inMenu = false;

String menuItems[] = {
  "1. Sensors",
  "2. Update speed",
  "3. WiFi status",
  "4. Send Tg",
  "5. Exit"
};

int lastBtnUp = HIGH;
int lastBtnOk = HIGH;

unsigned long lastRead = 0;
unsigned long lastMainUpdate = 0;
unsigned long readInterval = 2000;
unsigned long mainScreenInterval = 5000;

bool inSensorsDetail = false;
int detailStep = 0;

bool inSpeedSubmenu = false;
bool inWiFiSubmenu = false;
int wifiPage = 0;


String urlEncode(const String& str) {
  String encoded = "";
  char c;
  char code0;
  char code1;

  for (unsigned int i = 0; i < str.length(); i++) {
    c = str.charAt(i);

    if (isalnum(c)) {
      encoded += c;
    } else if (c == ' ') {
      encoded += "%20";
    } else {
      code1 = (c & 0x0F) + '0';
      if ((c & 0x0F) > 9) code1 = (c & 0x0F) - 10 + 'A';

      c = (c >> 4) & 0x0F;
      code0 = c + '0';
      if (c > 9) code0 = c - 10 + 'A';

      encoded += '%';
      encoded += code0;
      encoded += code1;
    }
  }

  return encoded;
}


void readSensors() {
  if (bmeOk) {
    t = bme.readTemperature();
    h = bme.readHumidity();
    p = bme.readPressure() / 100.0F;

    if (isnan(t)) t = -999;
    if (isnan(h)) h = -999;
    if (isnan(p) || p < 800) p = -999;
  } else {
    t = -999;
    h = -999;
    p = -999;
  }

  if (lightOk) {
    lux = max44009.readLux();
    if (isnan(lux)) lux = -999;
  } else {
    lux = -999;
  }
}


String buildTelegramMessage(String eventName) {
  String message = "station=" + String(STATION_SERIAL);

  if (eventName.length() > 0) {
    message += ", event=" + eventName;
  }

  if (t > -100) {
    message += ", temperature=" + String(t, 1);
  }

  if (h >= 0) {
    message += ", humidity=" + String(h, 1);
  }

  if (p > 800) {
    message += ", pressure=" + String(p, 1);
  }

  if (lux >= 0) {
    message += ", light=" + String(lux, 1);
  }

  return message;
}


bool sendToTelegram(String eventName) {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("Telegram send skipped: WiFi disconnected");
    return false;
  }

  readSensors();

  String message = buildTelegramMessage(eventName);

  if (message == "station=" + String(STATION_SERIAL) || message == "station=" + String(STATION_SERIAL) + ", event=" + eventName) {
    Serial.println("Telegram send skipped: no valid sensor data");
    return false;
  }

  WiFiClientSecure client;
  client.setInsecure();
  client.setTimeout(10000);

  String encodedMessage = urlEncode(message);
  String url = "/bot" + String(BOT_TOKEN) + "/sendMessage?chat_id=" + String(CHAT_ID) + "&text=" + encodedMessage;

  bool ok = false;
  bool httpOk = false;
  String response = "";

  if (client.connect("api.telegram.org", 443)) {
    client.print("GET " + url + " HTTP/1.1\r\n");
    client.print("Host: api.telegram.org\r\n");
    client.print("User-Agent: ESP8266\r\n");
    client.print("Connection: close\r\n\r\n");

    unsigned long start = millis();

    while (millis() - start < 8000) {
      while (client.available()) {
        String line = client.readStringUntil('\n');
        response += line;

        if (line.indexOf("HTTP/1.1 200 OK") >= 0) {
          httpOk = true;
        }

        if (line.indexOf("\"ok\":true") >= 0) {
          ok = true;
        }
      }
      delay(10);
    }

    Serial.println("Telegram message:");
    Serial.println(message);
    Serial.println("Telegram response:");
    Serial.println(response);
  } else {
    Serial.println("Telegram connection failed");
  }

  client.stop();

  if (httpOk || ok) {
    Serial.println("Sent to Telegram OK");
    return true;
  } else {
    Serial.println("Telegram send failed or response not confirmed");
    return false;
  }
}


String sensorValueHtml(float value, String unit, bool valid) {
  if (!valid) {
    return "<span class='value bad'>---</span><span class='unit'>" + unit + "</span>";
  }

  return "<span class='value'>" + String(value, 1) + "</span><span class='unit'>" + unit + "</span>";
}


void handleRoot() {
  readSensors();

  String html = "<!DOCTYPE html><html><head>";
  html += "<meta charset='UTF-8'>";
  html += "<meta name='viewport' content='width=device-width, initial-scale=1'>";
  html += "<meta http-equiv='refresh' content='10'>";
  html += "<title>ESP8266 Meteo Station</title>";
  html += "<style>";
  html += "body{font-family:Arial,sans-serif;background:#f4f4f4;color:#111;margin:0;padding:14px;text-align:center;box-sizing:border-box;overflow-x:hidden;}";
  html += "*{box-sizing:border-box;}";
  html += ".card{background:#fff;border:1px solid #ccc;border-radius:10px;padding:16px;margin:12px auto;max-width:760px;width:100%;}";
  html += ".grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;max-width:760px;width:100%;margin:0 auto;}";
  html += ".sensor{background:#fff;border:1px solid #ccc;border-radius:10px;padding:14px;min-width:0;overflow:hidden;}";
  html += ".sensor h2{font-size:20px;margin:0 0 12px 0;white-space:normal;font-weight:700;}";
  html += ".value{font-size:32px;font-weight:400;word-break:break-word;}";
  html += ".bad{color:#777;}";
  html += ".unit{font-size:20px;margin-left:5px;font-weight:400;}";
  html += "button{font-size:18px;padding:14px 22px;border:1px solid #111;border-radius:8px;background:#fff;color:#111;cursor:pointer;width:100%;max-width:360px;}";
  html += "button:hover{background:#eee;}";
  html += ".small{font-size:13px;color:#444;}";
  html += "@media(max-width:520px){.grid{grid-template-columns:1fr}.value{font-size:28px}.sensor h2{font-size:17px}}";
  html += "</style>";
  html += "</head><body>";

  html += "<div class='card'>";
  html += "<h1>Метеостанция ESP8266</h1>";
  html += "<p class='small'>Серийный номер: ";
  html += STATION_SERIAL;
  html += "</p>";
  html += "<p class='small'>IP: " + WiFi.localIP().toString() + "</p>";
  html += "</div>";

  html += "<div class='grid'>";

  html += "<div class='sensor'><h2>Температура</h2>";
  html += sensorValueHtml(t, "C", t > -100);
  html += "</div>";

  html += "<div class='sensor'><h2>Влажность</h2>";
  html += sensorValueHtml(h, "%", h >= 0);
  html += "</div>";

  html += "<div class='sensor'><h2>Давление</h2>";
  html += sensorValueHtml(p, "hPa", p > 800);
  html += "</div>";

  html += "<div class='sensor'><h2>Освещённость</h2>";
  html += sensorValueHtml(lux, "lx", lux >= 0);
  html += "</div>";

  html += "</div>";

  html += "<div class='card'>";
  html += "<h2>Telegram</h2>";
  html += "<form action='/send_tg' method='GET'>";
  html += "<button type='submit'>Отправить в Telegram</button>";
  html += "</form>";

  html += "</div>";



  html += "</body></html>";

  server.send(200, "text/html; charset=utf-8", html);
}


void handleSendTelegramWeb() {
  bool ok = sendToTelegram("manual_web");

  if (ok) {
    lastWebStatus = "сообщение отправлено";
  } else {
    lastWebStatus = "ошибка отправки";
  }

  lastWebSendTime = millis();

  String html = "<!DOCTYPE html><html><head>";
  html += "<meta charset='UTF-8'>";
  html += "<meta name='viewport' content='width=device-width, initial-scale=1'>";
  html += "<meta http-equiv='refresh' content='2; url=/'>";
  html += "<title>Telegram send</title>";
  html += "<style>";
  html += "body{font-family:Arial,sans-serif;background:#fff;color:#111;text-align:center;padding-top:60px;}";
  html += ".box{border:1px solid #111;border-radius:10px;padding:20px;max-width:420px;margin:auto;}";
  html += "a{color:#111;}";
  html += "</style>";
  html += "</head><body>";
  html += "<div class='box'>";

  if (ok) {
    html += "<h1>Отправлено</h1>";
    html += "<p>Показания отправлены в Telegram.</p>";
  } else {
    html += "<h1>Ошибка</h1>";
    html += "<p>Не удалось отправить показания.</p>";
  }

  html += "<p><a href='/'>Вернуться</a></p>";
  html += "</div>";
  html += "</body></html>";

  server.send(200, "text/html; charset=utf-8", html);
}


void showMainScreen() {
  lcd.clear();

  lcd.setCursor(0, 0);
  lcd.print("T:");
  if (t > -100) lcd.print(t, 2); else lcd.print("---");
  lcd.print(" H:");
  if (h >= 0) lcd.print(h, 2); else lcd.print("---");

  lcd.setCursor(0, 1);
  lcd.print("P:");
  if (p > 800) lcd.print(p, 2); else lcd.print("---");
  lcd.print(" L:");
  if (lux >= 0) lcd.print(lux, 2); else lcd.print("---");

}


void showMenu() {
  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print("MENU");
  lcd.setCursor(0, 1);
  lcd.print(menuItems[menuIndex]);
}


void showWiFiStatus() {
  lcd.clear();

  if (wifiPage == 0) {
    lcd.setCursor(0, 0);
    lcd.print("IP:");
    lcd.setCursor(0, 1);
    lcd.print(WiFi.localIP().toString().substring(0, 15));
  } else {
    lcd.setCursor(0, 0);
    lcd.print("RSSI:");
    lcd.setCursor(0, 1);
    lcd.print(WiFi.RSSI());
    lcd.print(" dBm");
  }
}


void showDetailSensors() {
  lcd.clear();

  switch (detailStep) {
    case 0:
      lcd.setCursor(0, 0);
      lcd.print("Temperature:");
      lcd.setCursor(0, 1);
      if (t > -100) {
        lcd.print(t, 2);
        lcd.print(" C");
      } else {
        lcd.print("--- C");
      }
      break;

    case 1:
      lcd.setCursor(0, 0);
      lcd.print("Humidity:");
      lcd.setCursor(0, 1);
      if (h >= 0) {
        lcd.print(h, 2);
        lcd.print(" %");
      } else {
        lcd.print("--- %");
      }
      break;

    case 2:
      lcd.setCursor(0, 0);
      lcd.print("Pressure:");
      lcd.setCursor(0, 1);
      if (p > 800) {
        lcd.print(p, 2);
        lcd.print(" hPa");
      } else {
        lcd.print("--- hPa");
      }
      break;

    case 3:
      lcd.setCursor(0, 0);
      lcd.print("Light:");
      lcd.setCursor(0, 1);
      if (lux >= 0) {
        lcd.print(lux, 2);
        lcd.print(" Lx");
      } else {
        lcd.print("--- Lx");
      }
      break;
  }
}


void handleButtons() {
  int btnUp = digitalRead(BTN_UP_PIN);
  int btnOk = digitalRead(BTN_OK_PIN);

  if (btnUp == LOW && lastBtnUp == HIGH) {
    if (inMenu && !inSensorsDetail && !inSpeedSubmenu && !inWiFiSubmenu) {
      menuIndex = (menuIndex + 1) % menuItemCount;
      showMenu();
    } else if (inSensorsDetail) {
      detailStep = (detailStep + 1) % 4;
      showDetailSensors();
    } else if (inWiFiSubmenu) {
      wifiPage = (wifiPage + 1) % 2;
      showWiFiStatus();
    }

    delay(150);
  }

  lastBtnUp = btnUp;

  if (btnOk == LOW && lastBtnOk == HIGH) {
    if (!inMenu && !inSensorsDetail && !inSpeedSubmenu && !inWiFiSubmenu) {
      inMenu = true;
      showMenu();
    } else if (inSensorsDetail) {
      inSensorsDetail = false;
      inMenu = true;
      detailStep = 0;
      showMenu();
    } else if (inSpeedSubmenu) {
      inSpeedSubmenu = false;
      inMenu = true;
      showMenu();
    } else if (inWiFiSubmenu) {
      inWiFiSubmenu = false;
      inMenu = true;
      wifiPage = 0;
      showMenu();
    } else if (inMenu) {
      int pot;
      int percent;

      switch (menuIndex) {
        case 0:
          inMenu = false;
          inSensorsDetail = true;
          detailStep = 0;
          showDetailSensors();
          break;

        case 1:
          inMenu = false;
          inSpeedSubmenu = true;
          lcd.clear();
          lcd.setCursor(0, 0);
          lcd.print("Update speed:");
          pot = analogRead(POT_PIN);
          percent = map(pot, 0, 1023, 0, 100);
          lcd.setCursor(0, 1);
          lcd.print(percent);
          lcd.print("%");
          break;

        case 2:
          inMenu = false;
          inWiFiSubmenu = true;
          wifiPage = 0;
          showWiFiStatus();
          break;

        case 3:
          inMenu = false;
          lcd.clear();
          lcd.print("Sending...");
          sendToTelegram("manual_lcd");
          delay(1500);
          inMenu = true;
          showMenu();
          break;

        case 4:
          inMenu = false;
          showMainScreen();
          break;
      }
    }

    delay(200);
  }

  lastBtnOk = btnOk;
}


void setup() {
  Serial.begin(115200);
  delay(1000);

  pinMode(BTN_UP_PIN, INPUT_PULLUP);
  pinMode(BTN_OK_PIN, INPUT_PULLUP);

  Wire.begin(4, 5);

  lcd.init();
  lcd.backlight();
  lcd.print("Loading...");

  bmeOk = bme.begin(BME_ADDR);
  lightOk = max44009.begin();

  lcd.setCursor(0, 1);
  if (!bmeOk && !lightOk) {
    lcd.print("Sensors error");
  } else {
    lcd.print("Sensors OK");
  }

  IPAddress staticIP(192, 168, 100, 55);
  IPAddress gateway(192, 168, 100, 1);
  IPAddress subnet(255, 255, 255, 0);
  IPAddress dns1(8, 8, 8, 8);
  IPAddress dns2(8, 8, 4, 4);

  WiFi.config(staticIP, gateway, subnet, dns1, dns2);
  WiFi.begin(ssid, password);

//   WiFi.mode(WIFI_STA);
// WiFi.begin(ssid, password);

  lcd.clear();
  lcd.print("WiFi...");

  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }

  lcd.clear();
  lcd.print("WiFi OK");
  lcd.setCursor(0, 1);
  lcd.print(WiFi.localIP().toString().substring(0, 14));

  server.on("/", handleRoot);
  server.on("/send_tg", handleSendTelegramWeb);
  server.begin();

  Serial.println();
  Serial.println("HTTP server started");
  Serial.print("IP: ");
  Serial.println(WiFi.localIP());

  readSensors();

  delay(2000);
  lcd.clear();
}


void loop() {
  unsigned long now = millis();

  if (now - lastRead >= readInterval) {
    lastRead = now;
    readSensors();
  }

  if (now - lastSend >= SEND_INTERVAL) {
    lastSend = now;
    sendToTelegram("auto");
  }

  server.handleClient();

  if (inSpeedSubmenu) {
    static int lastPercent = -1;
    int pot = analogRead(POT_PIN);
    int percent = map(pot, 0, 1023, 0, 100);

    if (percent != lastPercent) {
      lastPercent = percent;

      long newInterval = percent * 100L;
      if (newInterval < 500) newInterval = 500;
      if (newInterval > 10000) newInterval = 10000;

      long diff = newInterval - (long)readInterval;
      if (diff < 0) diff = -diff;

      if (diff > 50) {
        readInterval = (unsigned long)newInterval;

        lcd.clear();
        lcd.setCursor(0, 0);
        lcd.print("Update speed:");
        lcd.setCursor(0, 1);
        lcd.print(percent);
        lcd.print("% (");
        lcd.print(readInterval / 1000.0, 1);
        lcd.print(" sec)");
      }
    }

    delay(50);
  } else if (inSensorsDetail) {
    delay(50);
  } else if (!inMenu && !inWiFiSubmenu && !inSpeedSubmenu && !inSensorsDetail) {
    if (now - lastMainUpdate >= mainScreenInterval) {
      lastMainUpdate = now;
      showMainScreen();
    }
  }

  handleButtons();
  delay(10);
}
