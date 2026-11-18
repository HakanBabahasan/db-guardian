# DB Guardian

> *"Hiçbir değişiklik test edilmeden production'a gitmemeli."*

Production veritabanlarında yapılan değişikliklerin doğrudan uygulanması veri kaybı, kesinti ve geri dönülmesi zor hatalara yol açar. DB Guardian, her SQL değişikliğini yakalayan, klonlanmış bir ortamda test eden ve akıllı analiz sonucunda onaylayan ya da reddeden bir güvenlik katmanıdır. Amacı, insan hatasını pipeline'a sokmadan yakalamaktır.

---

## Hızlı Başlangıç

```bash
# 1. Repo'yu klonla
git clone https://github.com/HakanBabahasan/db-guardian.git
cd db-guardian

# 2. Ortam dosyasını oluştur
cp .env.example .env

# 3. Sistemi ayağa kaldır
docker compose up --build
```

API otomatik olarak `http://localhost:8000` adresinde başlar.
Swagger UI: `http://localhost:8000/docs`

> **Önemli:** Production'da `.env` dosyasındaki `JWT_SECRET_KEY` ve `BREAKGLASS_SECRET_KEY` değerlerini mutlaka değiştirin. Uygulama, varsayılan secret'lar ile production modunda başlamayı reddeder.

---

## Mimari

```
[Yazılımcı] ──► [Guardian API :8000] ──► [Production DB]
                       │
                       ├── [Clone DB]     (test ortamı)
                       ├── [App DB]       (audit log)
                       └── [/backups]     (snapshot'lar)
```

**Production DB, Clone DB ve App DB dışarıya kapalıdır.**
Yazılımcılar yalnızca Guardian API ile iletişim kurabilir.

---

## Pipeline (6 Aşama)

| Aşama | İşlem |
|-------|-------|
| 1 | **Komut filtresi** — WHERE'siz DELETE/UPDATE, DROP TABLE → anında blok |
| 2 | **Kuyruk** — Sıralı işlem garantisi |
| 3 | **Pre-op snapshot** — Production'ın tam yedeği |
| 4 | **Anlık klon** — SQL klona uygulanır, production'a dokunulmaz |
| 5 | **Diff analizi** — Satır sayısı, tip, NULL, constraint karşılaştırması |
| 6 | **Karar** — PASS / MANUAL_REVIEW / BLOCK |

---

## Karar Matrisi

| Karar | Koşul |
|-------|-------|
| `INSTANT_BLOCK` | WHERE'siz DELETE/UPDATE, DROP TABLE/DATABASE, TRUNCATE |
| `BLOCK` | CRITICAL risk, kolon silindi, SQL klona uygulanamadı |
| `MANUAL_REVIEW` | HIGH/MEDIUM risk → Break-glass (iki yönetici onayı) |
| `PASS` | LOW risk veya saf refactor → otomatik onay |

---

## Demo Kullanıcılar

> **Not:** Demo kullanıcılar yalnızca `APP_ENV=development` modunda oluşturulur. Production'da devre dışı kalır.

| Kullanıcı | Parola | Rol |
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

### 2. SQL Gönder

```bash
curl -X POST http://localhost:8000/api/execute \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "sql": "ALTER TABLE users ADD COLUMN phone VARCHAR(20)",
    "description": "Kullanıcılara telefon alanı ekleniyor"
  }'
```

### 3. İş Durumu Sorgula

```bash
curl http://localhost:8000/api/jobs/<JOB_ID> \
  -H "Authorization: Bearer <TOKEN>"
```

### 4. Sistem Durumu

```bash
curl http://localhost:8000/api/status \
  -H "Authorization: Bearer <TOKEN>"
```

### 5. Break-Glass Onayı (Yönetici)

```bash
# Günlük parolayı al (admin)
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
# Tüm testleri çalıştır
pytest

# Belirli bir modülü test et
pytest tests/test_command_filter.py -v

# Coverage raporu
pytest --cov=src --cov-report=term-missing
```

---

## Test Senaryoları

### ✅ Güvenli Değişiklik — Otomatik Onay

```sql
ALTER TABLE users ADD COLUMN phone VARCHAR(20);
```

### 🔴 Anında Blok — WHERE'siz DELETE

```sql
DELETE FROM users;
```

### 🔴 Anında Blok — DROP TABLE

```sql
DROP TABLE payments;
```

### ⚠️ Manuel İnceleme — Kolon Tipi Değişimi

```sql
ALTER TABLE payments ALTER COLUMN amount TYPE INTEGER;
```

### ⚠️ Manuel İnceleme — Kolon Silme

```sql
ALTER TABLE users DROP COLUMN email;
```

---

## Break-Glass Mekanizması

1. Risk yüksekse sistem `MANUAL_REVIEW` kararı üretir.
2. Yazılımcı bekler, yöneticilere bildirim gider.
3. **İki farklı yönetici** JWT girişi + günlük değişen parola ile onay verir.
4. Timeout (15 dk) dolunca sistem **bakım moduna** girer.

### Günlük Değişen Parola

Parola, kullanıcı bilgileri ve tarih üzerinden sunucu tarafındaki `BREAKGLASS_SECRET_KEY` ile HMAC-SHA256 kullanılarak üretilir. Algoritma public olsa bile secret olmadan parola hesaplanamaz.

---

## Sistem Modları

| Mod | Açıklama |
|-----|----------|
| `ACTIVE` | Normal çalışma |
| `MAINTENANCE` | Yazma kilitli, yalnızca okuma. Yönetici müdahalesi gerekli. |
| `MONITORING` | İzleme modu — komutlar geçer ama her şey loglanır. |

---

## Güvenlik Notları

- **JWT Secret:** Uygulama, varsayılan `JWT_SECRET_KEY` ile production modunda başlamayı reddeder. `.env` dosyasında güvenli bir secret tanımlayın.
- **Break-Glass Secret:** `BREAKGLASS_SECRET_KEY` de aynı şekilde production'da değiştirilmelidir.
- **CORS:** Varsayılan olarak yalnızca `http://localhost:3000` origininden gelen isteklere izin verilir. Production'da `ALLOWED_ORIGINS` değerini kendi domainlerinizle güncelleyin.
- **Demo kullanıcılar:** Yalnızca `APP_ENV=development` modunda aktiftir. Production'da otomatik olarak devre dışı kalır.
- **Production kullanıcı yönetimi:** Henüz harici bir kullanıcı deposu (DB, LDAP) entegrasyonu yoktur. Production'da kullanıcı yönetimi v2.0 kapsamında planlanmaktadır.

---

## MVP Kapsamı (v1.0)

- [x] Private network — DB'lere doğrudan erişim kapalı
- [x] Gateway — JWT kimlik doğrulama + yetki kontrolü
- [x] WHERE'siz DELETE/UPDATE, DROP TABLE/DATABASE → anında blok
- [x] Migration kuyruğu — sıralı işlem garantisi
- [x] Anlık klon + SQL testi (klon üzerinde)
- [x] Pre-operation otomatik backup (pg_dump)
- [x] Temel diff raporu (satır sayısı, tip, NULL, constraint)
- [x] Karar motoru (PASS / MANUAL_REVIEW / BLOCK / INSTANT_BLOCK)
- [x] İki yönetici break-glass mekanizması
- [x] Günlük değişen parola sistemi (HMAC-SHA256)
- [x] Bakım modu + izleme modu
- [x] Tam audit log

## v2.0 Yol Haritası

- [ ] Production kullanıcı yönetimi (DB/LDAP entegrasyonu)
- [ ] Akıllı diff motoru (REFACTOR tespiti geliştirilmiş)
- [ ] Dual-write mekanizması
- [ ] MySQL / MSSQL desteği
- [ ] E-posta / SMS bildirim entegrasyonu
- [ ] Geliştirici portalı (UI)
