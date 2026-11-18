# DB Guardian

> *"Hicbir degisiklik test edilmeden production'a gitmemeli."*

Production veritabanlarinda yapilan degisikliklerin dogrudan uygulanmasi veri kaybi, kesinti ve geri donulmesi zor hatalara yol acar. DB Guardian, her SQL degisikligini yakalayan, klonlanmis bir ortamda test eden ve akilli analiz sonucunda onaylayan ya da reddeden bir guvenlik katmanidir. Amaci, insan hatasini pipeline'a sokmadan yakalamaktir.

---

## Hizli Baslangic

```bash
# 1. Repo'yu klonla
git clone https://github.com/HakanBabahasan/db-guardian.git
cd db-guardian

# 2. Ortam dosyasini olustur
cp .env.example .env

# 3. Sistemi ayaga kaldir
docker compose up --build
```

API otomatik olarak `http://localhost:8000` adresinde baslar.
Swagger UI: `http://localhost:8000/docs`

> **Onemli:** Production'da `.env` dosyasindaki `JWT_SECRET_KEY` degerini mutlaka degistirin. Uygulama, varsayilan secret ile production modunda baslamayi reddeder.

---

## Mimari

```
[Yazilimci] --> [Guardian API :8000] --> [Production DB]
                       |
                       |-- [Clone DB]     (test ortami)
                       |-- [App DB]       (audit log)
                       \-- [/backups]     (snapshot'lar)
```

**Production DB, Clone DB ve App DB disariya kapalidir.**
Yazilimcilar yalnizca Guardian API ile iletisim kurabilir.

---

## Pipeline (6 Asama)

| Asama | Islem |
|-------|-------|
| 1 | **Komut filtresi** -- WHERE'siz DELETE/UPDATE, DROP TABLE -> aninda blok |
| 2 | **Kuyruk** -- Sirali islem garantisi |
| 3 | **Pre-op snapshot** -- Production'in tam yedegi |
| 4 | **Anlik klon** -- SQL klona uygulanir, production'a dokunulmaz |
| 5 | **Diff analizi** -- Satir sayisi, tip, NULL, constraint karsilastirmasi |
| 6 | **Karar** -- PASS / MANUAL_REVIEW / BLOCK |

---

## Karar Matrisi

| Karar | Kosul |
|-------|-------|
| `INSTANT_BLOCK` | WHERE'siz DELETE/UPDATE, DROP TABLE/DATABASE, TRUNCATE |
| `BLOCK` | CRITICAL risk, kolon silindi, SQL klona uygulanamadi |
| `MANUAL_REVIEW` | HIGH/MEDIUM risk -> Break-glass (iki yonetici onayi) |
| `PASS` | LOW risk veya saf refactor -> otomatik onay |

---

## Demo Kullanicilar

> **Not:** Demo kullanicilar yalnizca `APP_ENV=development` modunda aktiftir. Production'da devre disi kalir.

| Kullanici | Parola | Rol |
|-----------|--------|-----|
| `admin` | `admin123` | admin |
| `manager1` | `manager123` | manager |
| `manager2` | `manager456` | manager |
| `dev1` | `dev123` | developer |
| `dev2` | `dev456` | developer |

---

## API Rehberi

### 1. Token Al

```bash
curl -X POST http://localhost:8000/auth/token \
  -d "username=dev1&password=dev123"
```

### 2. SQL Gonder

```bash
curl -X POST http://localhost:8000/api/execute \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "sql": "ALTER TABLE users ADD COLUMN phone VARCHAR(20)",
    "description": "Kullanicilara telefon alani ekleniyor"
  }'
```

### 3. Is Durumu Sorgula

```bash
curl http://localhost:8000/api/jobs/<JOB_ID> \
  -H "Authorization: Bearer <TOKEN>"
```

### 4. Sistem Durumu

```bash
curl http://localhost:8000/api/status \
  -H "Authorization: Bearer <TOKEN>"
```

### 5. Break-Glass Onayi (Yonetici)

```bash
# Gunluk parolayi al (admin)
curl http://localhost:8000/api/breakglass/daily-password/manager1 \
  -H "Authorization: Bearer <ADMIN_TOKEN>"

# Onay ver
curl -X POST http://localhost:8000/api/breakglass/approve \
  -H "Authorization: Bearer <MANAGER1_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "job_id": "<JOB_ID>",
    "manager_id": "manager1",
    "daily_password": "<DAILY_PASSWORD>"
  }'
```

### 6. Audit Log

```bash
curl http://localhost:8000/api/audit/logs \
  -H "Authorization: Bearer <MANAGER_TOKEN>"
```

---

## Testler

```bash
# Tum testleri calistir
pytest

# Belirli bir modulu test et
pytest tests/test_command_filter.py -v

# Coverage raporu
pytest --cov=src --cov-report=term-missing
```

---

## Test Senaryolari

### Guvenli Degisiklik -- Otomatik Onay

```sql
ALTER TABLE users ADD COLUMN phone VARCHAR(20);
```

### Aninda Blok -- WHERE'siz DELETE

```sql
DELETE FROM users;
```

### Aninda Blok -- DROP TABLE

```sql
DROP TABLE payments;
```

### Manuel Inceleme -- Kolon Tipi Degisimi

```sql
ALTER TABLE payments ALTER COLUMN amount TYPE INTEGER;
```

### Manuel Inceleme -- Kolon Silme

```sql
ALTER TABLE users DROP COLUMN email;
```

---

## Break-Glass Mekanizmasi

1. Risk yuksekse sistem `MANUAL_REVIEW` karari uretir.
2. Yazilimci bekler, yoneticilere bildirim gider.
3. **Iki farkli yonetici** JWT girisi + gunluk degisen parola ile onay verir.
4. Timeout (15 dk) dolunca sistem **bakim moduna** girer.

### Gunluk Degisen Parola Algoritmasi

```
SHA-256(username + full_name_lowercase + birth_day + birth_year + YYYYMMDD)
     -> ilk 10 karakter, buyuk harf
```

---

## Sistem Modlari

| Mod | Aciklama |
|-----|----------|
| `ACTIVE` | Normal calisma |
| `MAINTENANCE` | Yazma kilitli, yalnizca okuma. Yonetici mudahalesi gerekli. |
| `MONITORING` | Izleme modu -- komutlar gecer ama her sey loglanir. |

---

## Guvenlik Notlari

- **JWT Secret:** Uygulama, varsayilan `JWT_SECRET_KEY` ile production modunda baslamayi reddeder. `.env` dosyasinda guvenli bir secret tanimlayin.
- **CORS:** Varsayilan olarak yalnizca `http://localhost:3000` origininden gelen isteklere izin verilir. Production'da `ALLOWED_ORIGINS` degerini kendi domainlerinizle guncelleyin.
- **Demo kullanicilar:** Yalnizca `APP_ENV=development` modunda aktiftir. Production'da otomatik olarak devre disi kalir.

---

## MVP Kapsami (v1.0)

- [x] Private network -- DB'lere dogrudan erisim kapali
- [x] Gateway -- JWT kimlik dogrulama + yetki kontrolu
- [x] WHERE'siz DELETE/UPDATE, DROP TABLE/DATABASE -> aninda blok
- [x] Migration kuyrugu -- sirali islem garantisi
- [x] Anlik klon + SQL testi (klon uzerinde)
- [x] Pre-operation otomatik backup (pg_dump)
- [x] Temel diff raporu (satir sayisi, tip, NULL, constraint)
- [x] Karar motoru (PASS / MANUAL_REVIEW / BLOCK / INSTANT_BLOCK)
- [x] Iki yonetici break-glass mekanizmasi
- [x] Gunluk degisen parola sistemi
- [x] Bakim modu + izleme modu
- [x] Tam audit log

## v2.0 Yol Haritasi

- [ ] Akilli diff motoru (REFACTOR tespiti gelistirilmis)
- [ ] Dual-write mekanizmasi
- [ ] MySQL / MSSQL destegi
- [ ] E-posta / SMS bildirim entegrasyonu
- [ ] Gelistirici portali (UI)
