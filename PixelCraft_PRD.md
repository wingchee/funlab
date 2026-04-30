# Product Requirements Document: PixelCraft (拼豆) Member Portal

## 1. Executive Summary
**PixelCraft** is a web-based platform designed for pixel art (拼豆 - Perler/Hama Beads) enthusiasts. The app simplifies the creation process by automatically converting standard images into grid-based patterns. Members can discover, search, and save designs, while the Admin manages the conversion and curation of high-quality content.

---

## 2. Target Audience
* **Hobbyists:** Users looking for specific patterns to recreate physically.
* **Beginners:** Users who need a clear grid and color guide to start.
* **Admin (Owner):** Curates the pattern library and manages server-side conversions.

---

## 3. User Roles & Permissions
| Role | Capabilities |
| :--- | :--- |
| **Guest** | Browse public pattern gallery; basic keyword search. |
| **Member** | Login/Sign up; "Favorite" patterns; access high-resolution bead maps; view color-coded legends. |
| **Admin** | Upload images; configure conversion settings (grid size, palette); edit/delete patterns; manage user base. |

---

## 4. Functional Requirements

### 4.1 Image-to-Bead Converter (Admin Tool)
* **Upload Engine:** Admin can upload JPG, PNG, or WEBP files.
* **Downscaling:** System reduces image resolution to standard bead board sizes (e.g., 29x29, 50x50, or custom).
* **Color Quantization:** The server maps image colors to specific physical bead brand palettes (e.g., Perler, Hama, Artkal).
* **Dithering Options:** Optional algorithms to improve detail in lower-resolution grids.

### 4.2 Search & Discovery
* **Keyword Search:** Search by tags or titles (e.g., "Anime," "Retro," "Animals").
* **Filters:** Filter by grid complexity (Easy/Small vs. Hard/Large).

### 4.3 Membership & Personalization
* **Favorites List:** Members can click a "Heart" icon to save designs to their "My Favorites" dashboard.
* **Progress Tracking:** A simple toggle to mark specific patterns as "Completed."

### 4.4 Bead Map Viewer
* **Interactive Grid:** A zoomable interface showing the bead pattern.
* **Color Key:** A list of required bead colors with their corresponding ID numbers and estimated bead count.
* **Export:** Option to download the final grid as a PDF or PNG.

---

## 5. Technical Workflow
1.  **Input:** Admin uploads a high-resolution image.
2.  **Processing:** * The server calculates the average color of blocks to create the grid.
    * **Euclidean Distance Mapping:** Matches each block to the nearest physical bead color using RGB/LAB color space distance.
3.  **Storage:** The original image, the converted grid data, and the color list are stored in the database.
4.  **Output:** Displayed as a clean web interface for the end member.

---

## 6. UI/UX Requirements
* **Responsive Design:** Must be optimized for tablets and mobile phones (common for users to place devices next to their bead board).
* **Grid Clarity:** The pattern viewer must have distinct grid lines and clear icons/numbers inside cells to differentiate similar colors.

---

## 7. Roadmap & Future Scope
* **Phase 1:** Core Admin upload, server conversion, and Member "Favorite" system.
* **Phase 2:** Community features (comments, user photo uploads of finished works).
* **Phase 3:** Integration with e-commerce for purchasing bead kits based on patterns.
