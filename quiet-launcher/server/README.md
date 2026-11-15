# Сервер «Друзья» (Cloudflare Worker + D1)

Бесплатный тариф Cloudflare. Код сервера: `worker.js`, таблицы: `schema.sql`.

## Развёртывание через панель
1. Workers & Pages → Create application → Workers → Hello World → назовите воркер `quiet-friends` → Deploy.
2. Storage & Databases → D1 → Create → имя `quiet-friends`. Откройте базу → Console и выполните содержимое `schema.sql`.
3. Воркер → Settings → Bindings → Add → D1 database: имя привязки строго `DB`, база `quiet-friends`.
4. Воркер → Edit code: замените всё содержимое на `worker.js`, нажмите Deploy.
5. Проверка: адрес воркера в браузере должен ответить `{"service":"quiet-friends","ok":true}`.

Адрес воркера прописан в `ql/endpoints.py` (`FRIENDS_API`).

## Что хранится
Ник, код друга, хэш секретного ключа (сам ключ только на компьютере пользователя), связи и заявки, а если пользователь
включил — список проектов Modrinth и время последней активности. Хэш IP используется только для ограничения частоты запросов.
Кнопка «Выйти из профиля» в лаунчере удаляет всё это с сервера.

## Проверка без Cloudflare (Node 22+)
```
node --no-warnings server/test_worker.mjs
python -m unittest tests.test_friends
```
D1 имитируется на встроенном `node:sqlite`, поэтому это проверка логики, а не самого Cloudflare.
