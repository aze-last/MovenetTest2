# DESIGN.md - CellWatch AI Design System

## Project Vision
**CellWatch AI** is a high-security, institutional monitoring system. The design language is **"Institutional Dark"**—optimized for low eye strain in control-room environments, prioritizing information density, high contrast for alerts, and a professional, non-flashy aesthetic.

---

## 1. Color Palette

### Base Layers
- **Deep Base**: `#06090c` (Main page backgrounds, dashboard base)
- **Panel Background**: `#0f161f` (Sidebars, header bars, large containers)
- **Card Background**: `#151f2b` (Widget cards, elevated sections)
- **Hero Background**: `#0a0e13` (Landing screens, login hero panel)

### Borders & Dividers
- **Default Border**: `#1e2c3a` (Card outlines, section dividers)
- **Subtle Border**: `#243648` (Muted separators)
- **Accent Glow**: `#3e709e` (Focused states, subtle highlight rails)

### Brand & Accents
- **Primary Accent**: `#4f84bb` (Primary buttons, active navigation, brand icons)
- **Accent Hover**: `#426f9b` (Hover states for primary elements)
- **Success**: `#50d186` (Online status, confirmed incidents)
- **Warning**: `#f2c94c` (Motion detected, system warnings)
- **Danger**: `#f25c5c` (High-confidence alerts, hardware failure, logout)

### Typography Colors
- **Main Text**: `#ffffff` (Headers, primary data)
- **Dim Text**: `#a2b5c7` (Sub-headers, descriptions)
- **Muted Text**: `#637a91` (Captions, timestamps, disabled states)

---

## 2. Layout Systems

### Navigation Bar (Top)
- **Background**: `#111821` with a `#243648` bottom border.
- **Button Palette**:
  - Idle: `#18212b`
  - Hover: `#213244`
  - Active: `#4f84bb` (Blue background with `#f3f7fb` text)

### Dashboard Grid
- **Header Section**: Large Bahnschrift/Segoe UI headers with a "Command Center" eyebrow label.
- **Metric Cards**: 4-column layout at the top for quick-look stats (Active Cams, Alerts, CPU, Disk).
- **Main Panels**: 2-column split for Live Feeds vs. Recent Incident Feed.

### Settings / Form Layouts
- **Scrollable Container**: Uses `#10161d` base.
- **Form Sections**: Grouped into Cards (`#1b2430`) with `#26384a` borders.
- **Form Controls**:
  - Labels: Aligned left, `#a2b5c7` color.
  - Inputs: `#182330` background, no border by default, `#3e709e` border on focus.

### Login Screen
- **Structure**: 50/50 vertical split.
- **Left Panel**: `#0a0e13` with a vertical `#4f84bb` accent rail on the far left.
- **Right Panel**: `#06090c` containing an elevated login card (`#121a24`).

---

## 3. Component Styling

### Buttons
- **Shape**: Rounded corners (Radius: 6-8px).
- **Typography**: Bold Helvetica/Segoe UI, 10-12pt.
- **Variants**:
  - **Standard**: Blue background (`#4f84bb`).
  - **Danger**: Red background (`#8e5a5a` or `#f25c5c`).
  - **Success**: Green background (`#42c08d` or `#50d186`).

### Cards & Panels
- **Styling**: Flat design, no heavy shadows.
- **Border**: 1px solid `#1e2c3a`.
- **Padding**: Uniform 15-20px internal padding.

---

## 4. Technical Constraints (MANDATORY)

- **Typography**: Use standard system fonts (Segoe UI, Bahnschrift, Helvetica).
- **No Letter Spacing**: **CRITICAL** - Do NOT use `letter_spacing` or `kerning` properties. The local CustomTkinter environment does not support them and will crash.
- **Dark Mode Only**: No light mode variants are permitted.
- **Interactive Feedback**: All buttons and interactive rows must have a visible hover state (usually +10% brightness or a specific hover hex from the palette).
