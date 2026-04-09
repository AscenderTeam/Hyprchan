<div align="center">

<img width="200" height="5000" alt="hyprchan_present" src="https://github.com/user-attachments/assets/976529e7-063f-4f35-8acd-69b3ae311c4c" />


# 🌌 HyprAI OS: Hyprchan

**The homeostatic system companion that lives in your Hyprland workspace.**

[![Python Version](https://img.shields.io/badge/python-3.11%2B-blue.svg?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-005571?style=for-the-badge&logo=fastapi)](https://fastapi.tiangolo.com/)
[![Hyprland](https://img.shields.io/badge/Hyprland-CC1111?style=for-the-badge&logo=linux&logoColor=white)](https://hyprland.org/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-336791?style=for-the-badge&logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![License](https://img.shields.io/badge/license-MIT-green.svg?style=for-the-badge)](LICENSE)

---

**Hyprchan** is a homeostatic system entity driven by a continuous kernel loop, multimodal perception, and a layered memory stack. She observes your workspaces, listens to your voice, and reacts to your presence with dynamic mood shifts and pixel-art animations.

[**Quick Start**](#-quick-start) • [**Features**](#-features) • [**Architecture**](#-architecture) • [**Commands**](#-cli-commands)

</div>

---

## 📸 Visuals

<div align="center">
  <table border="0">
    <tr>
      <td width="50%">
        <img src="https://github.com/AscenderTeam/Hyprchan/raw/feature/memory-update/public/assets/readme/tui_screenshot.png" width="100%" alt="Rich TUI Interface">
        <p align="center"><i>Live Rich TUI with telemetry and memory snapshots.</i></p>
      </td>
      <td width="50%">
        <img src="https://github.com/AscenderTeam/Hyprchan/raw/feature/memory-update/public/assets/readme/overlay_example.png" width="100%" alt="Hyprland Overlay">
        <p align="center"><i>Animated Hyprland overlay with tool-calling capabilities.</i></p>
      </td>
    </tr>
  </table>
</div>

---

## 🚀 Quick Start

Getting Hyprchan running is simple. Just install and run the setup wizard.

### 1. Installation
```bash
pip install hyprchan
```

### 2. Setup Wizard
Run the interactive setup to configure your LLM provider, memory (Postgres/Redis), and system services.
```bash
hyprchan wizard setup
```

### 3. Launch the TUI
Once setup is complete, wake her up and start chatting:
```bash
hyprchan tui
```

---

## ✨ Features

*   **🧠 Layered Memory Stack:** Brain-inspired architecture with **Short-Term (Redis)**, **Long-Term (Postgres + pgvector)**, and **Working Memory**.
*   **🌙 Sleep & Dreaming:** Automatically distills events into semantic facts during consolidation cycles. She literally *dreams* about your interactions.
*   **🎭 Dynamic Mood Dynamics:** Internal scalars (`valence`, `energy`, `fatigue`) drive her personality. Sustained interaction or rudeness shifts her stance in real-time.
*   **👁️ Multimodal Perception:**
    *   **Vision:** Webcam face/motion detection and periodic desktop snapshots.
    *   **Audio:** Continuous speech-to-text via **Faster-Whisper** with auto-language detection.
    *   **OS:** Monitors Hyprland workspace switches and window focus events.
*   **🎨 LLM-Driven Animations:** The assistant can trigger poses (`idle`, `depressed`, `sleeping`) and move herself across your screen using custom tools.

---

## 🏗️ Architecture

Hyprchan operates on a **Continuous Kernel Loop** where perception preempts cognition.

### The Perception-to-Mood Pipeline
1.  **Controllers:** Emit raw OS/Voice/Vision events.
2.  **Toggle Detector:** Filters high-frequency "noise" from actual activity.
3.  **Activity Detector:** Calculates macro-pressure on her attention.
4.  **Mood Engine:** Updates internal scalars based on interaction quality ($d$ delta) and phase fatigue.
5.  **Logit Bias:** Mood scalars are projected into token-level biases, subtly altering her speech patterns.

---

## 💻 CLI Commands

Hyprchan comes with a powerful CLI for management and interaction.

| Command | Description |
| :--- | :--- |
| `hyprchan wizard setup` | Launches the interactive configuration master. |
| `hyprchan tui` | Opens the live Rich terminal interface. |
| `hyprchan serve` | Starts the FastAPI backend daemon. |
| `hyprchan extensions` | Manage built-in extensions (Hyprgram, HyprX). |
| `hyprchan status` | Check the health of the kernel and perception services. |

---

<div align="center">
  <sub>Built with the <b>Ascender Framework</b>. Maintained by <b>Ascender Team</b> and <b>Hyprland Community Enthusiasts</b>.</sub>
</div>
