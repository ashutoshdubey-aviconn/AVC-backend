# Frontend on the test server

Since 2026-11-17 the test server serves the current frontend
(`Aviconncorp-new-migrated-frontend`, branch `main`) at **http://43.204.53.81/**.
Every call (login, data, alarms, catch-up spread, baseline setup) goes to the
same server's `/api/` (nginx → Django on 127.0.0.1:8000), so it shows the
**test database** only. Main is not used.

## Local dev server

Since 2026-11-17 `environment.ts` and `environment.prod.ts` also point `apiUrl`
to `http://43.204.53.81/api/`, so `ng serve` (localhost:4200) uses the test
server for every call too (it used to log in against main).

## Build configuration

`ng build --configuration testserver`:
- `src/environments/environment.testserver.ts`: `apiUrl` and `alarmApiUrl` = `/api/`
- replaces both `environment.ts` and `environment.prod.ts` (three services
  import `environment.prod` directly)
- output `dist/movie-rater-web-testserver/browser`

## Deploy (replace)

```bash
cd ~/Aviconncorp-new-migrated-frontend
npx ng build --configuration testserver
tar czf - -C dist/movie-rater-web-testserver/browser . | ssh ubuntu@43.204.53.81 \
  'S=~/django_project/.work/frontend_$(date +%Y%m%d); rm -rf $S; mkdir -p $S; tar xzf - -C $S;
   sudo tar czf ~/django_project/backups/deploy/frontend_before_$(date +%Y%m%d).tgz -C /var/www/html movie-rater-web;
   sudo rsync -a --delete $S/ /var/www/html/movie-rater-web/;
   sudo chown -R www-data:www-data /var/www/html/movie-rater-web'
```

nginx (`/etc/nginx/sites-enabled/warehouse`) serves `/var/www/html/movie-rater-web`
with `try_files ... /index.html`, so deep links (`/dashboard`) work. No nginx
change was needed.

## Roll back

```bash
ssh ubuntu@43.204.53.81 'sudo rsync -a --delete /var/www/html/movie-rater-web_before_20261117/ /var/www/html/movie-rater-web/'
```

(or untar `~/django_project/backups/deploy/frontend_before_20261117.tgz` into `/var/www/html/`).
The replaced build was from 24 Aug 2026 and called `http://43.204.53.81:8000/api/`.

## Notes

- Log in at http://43.204.53.81/ (plain HTTP: the certificate is for
  asem.aviconncorp.com). The session is per address, separate from main's.
- `GET /api/tokens/` answers 404 on test and main alike (old frontend call, harmless).
