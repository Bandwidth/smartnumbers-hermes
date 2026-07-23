# Smartnumbers plugin installed

1. The installer prompted for `TRANSCRIPT_LISTENER_API_KEY`. If it was not set,
   add it to `$HERMES_HOME/.env`.
2. Configure `plugins.entries.smartnumbers.stream_url` and set
   `plugins.entries.smartnumbers.run_listener: true` in `$HERMES_HOME/config.yaml`.
3. Git installation does not install Python dependencies. In the Python
   environment that runs Hermes, install `websockets` if it is unavailable:

   ```sh
   python -m pip install 'websockets>=14,<16'
   ```

4. Restart the gateway:

   ```sh
   hermes gateway restart
   ```

The complete configuration reference is in this plugin's `README.md`.
