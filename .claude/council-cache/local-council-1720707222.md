> **Local council** — these perspectives all come from Claude playing different
> roles, not from different AI vendors. Treat agreement as a shared starting
> point to pressure-test, not as independent confirmation.

## 🗳️ Devil's Advocate

### Position
Options 2 and 3 are dangerous half-measures that keep the laptop teetering on the edge of its hardware limits during a live Capstone presentation. You must use Option 1 (4 RTSP over Ethernet).

### Key points
- Option 2 (distributing USB hubs) assumes the internal laptop traces actually map to separate root hubs with dedicated bandwidth. On budget gaming laptops like the TUF, multiple physical ports often share a single internal multiplexer, meaning you're just moving the bottleneck, not removing it.
- Option 3 (MJPEG compression) trades USB bandwidth for CPU decoding overhead. The CPU now has to decompress 4 MJPEG streams before even starting YOLO/MoveNet inference, which could tank your FPS.
- If a USB cable gets bumped during the presentation, OpenCV will drop the feed. Ethernet is physically latched and network cameras auto-reconnect robustly.

### Risks & blind spots
Relying entirely on RTSP over a network switch introduces network latency. If the switch buffers packets or the cameras lag, you might see a 1-2 second delay between reality and the screen, which could look bad during a live demo.

### Confidence
`high` — Hardware bottlenecks on consumer laptops are merciless. Offload the capture to external IP cameras.

## 🗳️ Simplicity Champion

### Position
Option 1 (4 RTSP over Ethernet) is the only path that eliminates hardware juggling and complex OpenCV parameter tuning, giving you a clean, unified architecture.

### Key points
- Treating all 4 cameras identically (as RTSP streams) means you write one robust connection pipeline in `camera_view.py`. You don't have to maintain separate logic for USB initialization vs. RTSP initialization.
- You already built a bulletproof RTSP watchdog with background thread releasing and timeout recovery. Why not use it for all 4 feeds?
- Option 2 requires remembering exactly which physical port each camera plugs into. One wrong plug on demo day breaks the system.
- Option 3 requires trusting that cheap USB webcams actually support and correctly report MJPEG capabilities to OpenCV on Windows, which is notoriously buggy.

### Risks & blind spots
You need physical infrastructure (a router/switch and 4 power adapters) for the IP cameras, making the setup less portable than tossing a few USB webcams in a backpack.

### Confidence
`high` — Uniform architectures are always easier to debug than mixed-mode architectures.

## 🗳️ Security Auditor

### Position
From an integrity and isolation standpoint, Option 1 (RTSP over a dedicated local Ethernet switch) provides the most robust and isolated data path.

### Key points
- Connecting the cameras via an isolated, offline Ethernet switch ensures no external network traffic interferes with the camera feeds.
- USB connections on Windows are susceptible to device driver crashes that can take down the entire OS or Python process. Network streams are sandboxed—the worst they can do is drop a TCP connection.
- A dedicated Ethernet subnet for the 4 Tapo cameras means you can lock down their IPs and ensure the OS firewall ignores everything else.

### Risks & blind spots
If you connect the Tapo cameras to the university/building Wi-Fi instead of a dedicated closed-loop router, you expose the streams to external congestion, packet sniffing, or DHCP lease drops.

### Confidence
`medium` — Security isn't the primary constraint here, but hardware isolation strongly favors the Ethernet approach.

## 🗳️ Scalability Architect

### Position
Option 1 (RTSP via Ethernet) is the only horizontally scalable architecture. It allows you to eventually move the inference off the laptop entirely if needed.

### Key points
- USB bandwidth is a hard physical ceiling. Ethernet gives you Gigabit throughput, which is more than enough for dozens of highly compressed H.264 streams.
- If you use RTSP, the physical location of the cameras is decoupled from the laptop. You can place cameras 100 feet away using cheap Cat6 cable, whereas USB is limited to a few meters before requiring active repeaters.
- Processing compressed H.264 video using hardware decoding (if available) is vastly more scalable than processing raw uncompressed YUYV video from USB sensors.

### Risks & blind spots
Decoding 4 H.264 streams simultaneously still requires CPU/GPU resources. While you solved the USB bandwidth limit, you might immediately hit a CPU bottleneck during the video decoding phase before inference even begins.

### Confidence
`high` — Networked cameras are the industry standard for multi-camera VMS (Video Management Systems) for exactly this reason.

---

## 🔬 Synthesis

### Shared starting points
Every single council member forcefully rejected Options 2 and 3 in favor of **Option 1 (4 RTSP cameras over Ethernet)**. They all recognized that relying on laptop USB controllers for multiple video streams introduces physical and software fragility that is unacceptable for a Capstone deployment.

### Genuine tensions
There is a tension between **Portability vs. Stability**. The Simplicity Champion noted that carrying 4 IP cameras and a network switch is bulky. However, the Devil's Advocate countered that USB hardware bottlenecks on gaming laptops are unpredictable and unforgiving. Given that this is a Capstone defense, stability must win. 

### Blind spots
The Scalability Architect highlighted the next potential bottleneck: **Decode Overhead**. By shifting the burden from the USB controller to the CPU/Network, the laptop now has to decode four H.264 streams simultaneously. While the I/O locking issue is solved, you must monitor CPU usage closely to ensure the decoders don't starve YOLO/MoveNet of compute cycles.

### Suggested direction
**Commit to Option 1: Four Tapo C200c cameras connected via a dedicated Gigabit router/switch directly into the laptop's Ethernet port.** 
- Treat all cameras uniformly in code.
- Avoid the building's Wi-Fi; bring your own cheap offline router to act as the switch so the network is 100% isolated and interference-free.
- Rely on the robust RTSP watchdog you've already built to handle any stream hiccups.
