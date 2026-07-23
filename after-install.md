# Smartnumbers plugin installed

1. Connect this Hermes profile to Smartnumbers:

   ```sh
   hermes smartnumbers setup
   ```

   If the browser runs on a different machine or Hermes runs in Docker, use:

   ```sh
   hermes smartnumbers setup --manual-paste --no-browser
   ```

   Open the printed URL in the browser. After approval, copy the complete
   loopback redirect URL from the browser address bar and paste it into the
   terminal. A browser connection error for that loopback URL is expected.

2. Git installation does not install Python dependencies. In the Python
   environment that runs Hermes, install `websockets` if it is unavailable:

   ```sh
   python -m pip install 'websockets>=14,<16'
   ```

3. Restart the gateway:

   ```sh
   hermes gateway restart
   ```

4. Verify the connection:

   ```sh
   hermes smartnumbers status
   ```

The complete configuration reference is in this plugin's `README.md`.
