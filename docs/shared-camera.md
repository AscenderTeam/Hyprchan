# Use the FaceTime camera in OBS and Hyprchan together

The physical Asahi camera has one owner: a small, independent FFmpeg feeder.
It copies NV12 frames to two loopback outputs without encoding. OBS and Hyprchan
can open in either order, and neither depends on the other application's process.

| Consumer | Device in the tested setup | Name |
| --- | --- | --- |
| OBS camera input | `/dev/video2` | Hyprchan Shared Camera |
| Hyprchan vision | `/dev/video3` | Hyprchan Camera Context |
| Feeder only | `/dev/v4l/by-path/platform-384000000.isp-video-index0` | FaceTime HD Camera |

The existing OBS virtual camera at `/dev/video0` stays separate. On the installed
v4l2loopback 0.15.4, two capture clients competing for a single loopback encounter
`VIDIOC_S_FMT: Device or resource busy`. Separate outputs avoid that limitation.
Hyprchan automatically prefers the context output by its label, and refuses to
probe a physical camera another process already owns. `HYPRCHAN_CAMERA_INDEX`
still overrides discovery.

The feeder starts when either output has an open consumer and releases the
physical camera five seconds after the last consumer closes. OBS can keep a
camera open even when its scene is hidden. Loopbacks remain discoverable while
idle and replace a stopped feed with black after two seconds. A stalled feeder
is stopped and retried with a five-second delay. No frames are recorded by this
service; the ordinary Hyprchan visual-context path still sends its snapshots to
the configured model when capture is enabled.

## Setup with existing dependencies

This setup uses the already installed `v4l2loopback` module, its matching build
header, a C compiler, FFmpeg, `v4l2-ctl`, `fuser`, Python and systemd. The supplied
units target the tested Asahi camera path and free device numbers 2/3; adjust
those before installing on another machine. The helper refuses an existing
loopback with another label and never unloads the module or replaces a device.
No system package installation or upgrade is performed.

From the repository root:

```sh
cc -O2 -Wall -Wextra -I /usr/src/v4l2loopback-0.15.4 scripts/create_shared_camera.c -o /tmp/hyprchan-camera-device
sudo install -Dm755 /tmp/hyprchan-camera-device /usr/local/libexec/hyprchan-camera-device
sudo install -Dm644 scripts/systemd/hyprchan-camera-devices.service /etc/systemd/system/hyprchan-camera-devices.service
sudo systemctl daemon-reload
sudo systemctl enable --now hyprchan-camera-devices.service
install -Dm755 scripts/shared_camera_feed.py "$HOME/.local/libexec/hyprchan/shared_camera_feed.py"
install -Dm644 scripts/systemd/hyprchan-camera-feed.service "$HOME/.config/systemd/user/hyprchan-camera-feed.service"
systemctl --user daemon-reload
systemctl --user enable --now hyprchan-camera-feed.service
```

In the existing OBS camera input, choose **Hyprchan Shared Camera**, NV12 and
1920×1080. Release its old physical-camera input before starting the feeder.
Keep the source itself so its filters, transforms and scene references survive.
Start Hyprchan normally with `hyprchan`; the context output is selected by label.
The active desktop user's normal udev `uaccess` permission grants device access.

To undo sharing, disable both units, then select the physical camera in one
application at a time. Remove the installed unit/helper files if no longer
needed. The added loopbacks disappear on reboot; the existing OBS virtual camera
does not need to be removed.

## Verification

The [live check](../benchmarks/codex-rp/results/shared-camera-20261018.json) exercised
both start orders, confirmed changing nonblank OBS frames and simultaneous
Hyprchan `screen` + `webcam` context, and confirmed the camera was released after
both readers closed. OBS was not restarted. Frame inspection stayed in memory;
the report contains metadata only. Capture is configured for 1080p/30; this
check does not measure 30 unique frames per second. Startup units were enabled
and validated without rebooting the machine.

References: [v4l2loopback](https://github.com/v4l2loopback/v4l2loopback/blob/v0.15.4/README.md),
[FFmpeg V4L2](https://ffmpeg.org/ffmpeg-devices.html#video4linux2_002c-v4l2),
[systemd services](https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html).
