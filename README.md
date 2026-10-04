# Voltdeer RS073 Home Assistant integration

A custom integration that polls the Voltdeer RS073's local HTTP status page. It identifies the device as Voltdeer RS073 (not Shelly) and uses the JSON response at `http://<meter-ip>/` on port 80.

## Install with HACS

1. In Home Assistant, open **HACS → Integrations**.
2. Open the menu in the upper-right and choose **Custom repositories**.
3. Add `https://github.com/dinpin/ha-voltdeer-rs073` and select **Integration** as the category.
4. Find **Voltdeer RS073** in HACS, download it, and restart Home Assistant.
5. If Home Assistant discovers the meter's `_http._tcp.local.` mDNS announcement and can reach its HTTP root page, it will offer automatic setup. Otherwise, open **Settings → Devices & services → Add integration**, select **Voltdeer RS073**, and enter the meter's local IP address or hostname, such as `10.2.2.249`.

HACS can install updates for this repository after it is added as a custom repository. Alternatively, install manually by copying `custom_components/voltdeer_rs073` into `<config>/custom_components/` and restarting Home Assistant.

The integration polls every 5 seconds by default. Under **Settings → Devices & services → Voltdeer RS073 → Configure**, you can change the polling interval (0.1–3600 seconds; fractional values are supported), include or exclude electrical measurements and diagnostic sensors, and exclude specific sensors. Sensor exclusions accept comma-separated leaf keys (for example, `rssi`) or full dotted JSON paths (for example, `wifi.rssi`). Both sensor groups are enabled by default. Sensors are created for scalar values from `em:0`, `emdata:0`, `wifi`, `sys`, and other components, including fields first seen in later responses. Known electrical readings receive Home Assistant units and device classes. The integration exposes total import/export energy sensors by summing the three phase counters, because the meter's aggregate `total_act` and `total_act_ret` fields may be invalid. Use **Total Import Energy (Phase Sum)** and **Total Export Energy (Phase Sum)** in the Energy dashboard. The endpoint must return JSON containing `em:0`.
