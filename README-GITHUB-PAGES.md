# CampusBite KPRCAS

## Pages

- `index.html` is the start page. Choose Student or Admin on each visit; the Admin login link is also highlighted at the top of the welcome card.
- `student-login.html` is the separate student sign-in.
- `student.html` is the student portal.
- `admin.html` is the separate admin sign-in and dashboard.
- Shop owners also sign in through `admin.html`; each shop account can only view and update orders assigned to its shop.
- `shop.html` is the student food menu and ordering page.
- The order page includes a direct Admin login link in its header.
- Homepage search opens the menu with matching meals pre-filtered. The order page search suggests menu items while typing, and its realistic food-photo carousel can be swiped or advanced with the arrows. All pages include rotating, swipeable food-photo backgrounds.
- The welcome page plays `campusbite-intro.mp4` with an animated-logo overlay and a skip option. When playback is supported, the welcome page appears after the entire video finishes; unsupported playback shows the logo intro before continuing.
- Student sign-in offers demo Student ID/PIN and sample mobile/demo-code modes. Mobile mode does not send an SMS or reveal a password.
- Admin analytics include daily revenue and order-volume bars with a revenue trend line. The map shows KPRCAS locations only; it does not track a visitor's device location. WhatsApp and SMS delivery are not connected.
- `local_backend.py` runs an optional local SQLite server. With Python 3.10 or later installed, run `py .\local_backend.py` and open `http://127.0.0.1:8765/`. It creates `data/campusbite.sqlite3` on first run and connects local admin sign-in, student sign-in, orders, and admin edits to that database.
- The local demo starts with eight shops: New Canteen Shops 1–4 and Old Canteen Shops 1–4. The student menu shows the shop name for each food item, and each order is sent only to that item's shop.
- The menu includes 47 items across all eight shops, with clearly labelled Veg and Non-Veg choices, jam buns, bun butter jam, palkova buns, egg and chicken foods, freshly squeezed juices, and chilled cool drinks. Existing local database and browser menu edits are preserved when the new items are added.
- Every stall manager has a separate account ID and shop-scoped order queue. Shopkeepers sign in through the Admin login page; account IDs and passwords are not printed on the sign-in page. After local startup, the global admin opens **Students & staff**, finds each manager’s account ID there, and sets a different private password for each shop before sharing its login details directly with that keeper. Shop owners can only view and update orders from their assigned shop.

## Publish with GitHub Pages

1. Upload all files and this project's assets to the root of a GitHub repository.
2. Commit the upload to the `main` branch.
3. In **Settings → Pages**, select **Deploy from a branch**, then choose **main** and **/(root)**.
4. After deployment, open the URL shown in Pages settings. It should show the Student/Admin start page.

## Run with local SQLite

Install Python 3.10 or later if needed. On Windows, run `py .\local_backend.py`
from the project folder, then open `http://127.0.0.1:8765/`. The server listens only on
the local computer. Demo sign-ins are `admin` / `CampusBite@123` and student
IDs `cb1024`, `cb2088`, or `cb3041` / `1234`. Shop manager accounts are provisioned
with unique, randomly generated initial passwords; the global admin must assign
each shop its own private password in **Students & staff** before a keeper can sign in.
Set a private
`CAMPUSBITE_ADMIN_PASSWORD` before the first run to replace the local demo
admin password. SQLite data is stored in `data/campusbite.sqlite3`.

This Python server cannot run on GitHub Pages. GitHub Pages deployment stays a
browser-local demo. A hosted backend is needed for shared,
internet-accessible accounts and orders. Never expose this local-only server
to the public internet.

## Demo-only security and storage

When hosted on GitHub Pages or opened as static files, authentication and data
remain a browser-local demo and are not shared between visitors. The optional
SQLite server adds password-hashed local accounts and server-checked student
orders on the computer running it, but is not a hosted, multi-user internet
backend. Do not use real payment details on either demo.
