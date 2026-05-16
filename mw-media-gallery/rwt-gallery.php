<?php
// At the very top of gallery.php
// 1. Find the path to MediaWiki's entry point
$mwPath = __DIR__; // If gallery.php is in the root
require_once "$mwPath/includes/WebStart.php";

// 2. Access the MediaWiki context
$context = RequestContext::getMain();
$user = $context->getUser();

// 3. Check if user is logged in (uncomment to enable)

if (!$user->isRegistered()) {
    die("Access Denied: You must be logged in to view this gallery.");
}

$raw_images = $_POST['images'] ?? [];
$image_list = array_values(array_filter($raw_images, function($url) {
    return filter_var($url, FILTER_VALIDATE_URL) || str_starts_with($url, '/images/');
}));

if (empty($image_list)) {
    die("<body style='background:#000;color:#fff;font-family:sans-serif;display:flex;justify-content:center;align-items:center;height:100vh;'>No images received via POST.</body>");
}

// Optional Table of Contents (strictly optional)
// Accepts either:
//  - Associative array: toc[5]="Introduction" (1-based page numbers as keys)
//  - JSON string of same, or array of {page: N, title: "..."} / {index, name}
$toc = [];
$toc_raw = $_POST['toc'] ?? [];
if (!empty($toc_raw)) {
    if (is_string($toc_raw)) {
        $decoded = json_decode($toc_raw, true);
        if (json_last_error() === JSON_ERROR_NONE && is_array($decoded)) {
            $toc_raw = $decoded;
        }
    }
    if (is_array($toc_raw)) {
        foreach ($toc_raw as $key => $value) {
            if (is_array($value)) {
                $page = $value['page'] ?? $value['index'] ?? $value[0] ?? null;
                $title = $value['title'] ?? $value['name'] ?? $value[1] ?? '';
                if ($page !== null && $title !== '') {
                    $toc[] = ['page' => (int)$page, 'title' => trim((string)$title)];
                }
            } elseif (is_numeric($key) && !empty($value)) {
                $toc[] = ['page' => (int)$key, 'title' => trim((string)$value)];
            }
        }
        // Sort and dedupe
        usort($toc, function($a, $b) { return $a['page'] <=> $b['page']; });
        $seen = [];
        $toc = array_values(array_filter($toc, function($item) use (&$seen) {
            if (in_array($item['page'], $seen, true)) return false;
            $seen[] = $item['page'];
            return true;
        }));
    }
}
?>
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=5.0, user-scalable=yes">
    <title>Pro Wiki Gallery</title>
    <style>
        :root { --bg: #000; --ui-bg: rgba(20, 20, 20, 0.9); --accent: #36c; }
        
        body, html { margin: 0; padding: 0; width: 100%; height: 100%; background: var(--bg); overflow: hidden; font-family: sans-serif; }

        /* The Viewer fills the whole screen, but we use padding to stay clear of UI */
        #viewer { 
            position: absolute; top: 0; left: 0; right: 0; 
            bottom: 90px; /* Leave space for filmstrip */
            display: flex; align-items: center; justify-content: center; 
            overflow: auto; 
            touch-action: pan-x pan-y pinch-zoom; 
            -webkit-overflow-scrolling: touch;
        }

        .slide { 
            max-width: 100%; max-height: 100%; 
            object-fit: contain; display: none; 
            cursor: zoom-in;
            transition: transform 0.05s linear;
        }
        .slide.active { display: block; }

        /* UI Elements */
        .counter { 
            position: fixed; top: 15px; right: 15px; 
            color: white; background: var(--ui-bg); 
            padding: 6px 12px; border-radius: 15px; z-index: 1000;
        }

        #close-zoom {
            display: none; position: fixed; top: 15px; left: 15px; z-index: 1000;
            padding: 10px 18px; background: var(--accent); color: white;
            border: none; border-radius: 5px; font-weight: bold; cursor: pointer;
        }

        #filmstrip { 
            position: fixed; bottom: 0; left: 0; width: 100%; height: 90px; 
            background: var(--ui-bg); display: flex; overflow-x: auto; 
            padding: 5px; gap: 8px; align-items: center; z-index: 900;
            border-top: 1px solid #333;
        }

        .thumb-slot { 
            flex: 0 0 65px; height: 75px; background: #222; 
            display: flex; align-items: center; justify-content: center; 
            cursor: pointer; border: 2px solid transparent; border-radius: 4px; 
            overflow: hidden; color: #555; font-size: 11px;
        }
        .thumb-slot.active { border-color: var(--accent); background: #333; color: #fff; }
        .thumb-slot img { width: 100%; height: 100%; object-fit: cover; }

        /* TOC Button */
        #toc-btn {
            position: fixed; top: 15px; left: 70px; z-index: 1000;
            background: var(--ui-bg); color: white; border: none;
            padding: 8px 14px; border-radius: 5px; cursor: pointer;
            font-size: 15px; line-height: 1;
        }

        /* TOC Overlay */
        .toc-overlay {
            position: fixed; inset: 0; background: rgba(0,0,0,0.92); z-index: 2000;
            display: none; align-items: center; justify-content: center; padding: 20px;
        }
        .toc-panel {
            background: #1a1a1a; border: 1px solid #333; border-radius: 8px;
            width: 100%; max-width: 420px; max-height: 70vh; overflow-y: auto;
            box-shadow: 0 10px 30px rgba(0,0,0,0.6);
        }
        .toc-header {
            padding: 16px 20px; border-bottom: 1px solid #333; font-weight: bold; color: #fff;
            display: flex; justify-content: space-between; align-items: center; font-size: 1.05rem;
        }
        .toc-close {
            background: none; border: none; color: #aaa; font-size: 24px; cursor: pointer; line-height: 1; padding: 0 4px;
        }
        .toc-close:hover { color: #fff; }
        .toc-list {
            padding: 4px 0;
        }
        .toc-item {
            padding: 13px 20px; color: #ddd; cursor: pointer; border-bottom: 1px solid #222;
            display: flex; gap: 14px; align-items: flex-start; transition: background 0.1s;
        }
        .toc-item:hover { background: #252525; color: #fff; }
        .toc-item:last-child { border-bottom: none; }
        .toc-page {
            flex-shrink: 0; background: #2a2a2a; color: #36c; font-size: 12px; font-weight: 700;
            padding: 3px 9px; border-radius: 4px; min-width: 30px; text-align: center; margin-top: 1px;
        }
        .toc-title { flex: 1; line-height: 1.35; font-size: 0.97rem; }

        /* State Changes for Zoom Mode */
        body.is-zoomed #viewer { 
            bottom: 0; 
            overflow: hidden;
        }
        body.is-zoomed #filmstrip, 
        body.is-zoomed .counter, 
        body.is-zoomed #toc-btn { 
            display: none; 
        }
        body.is-zoomed #close-zoom { display: block; }
    </style>
</head>
<body id="main-body">

<button id="close-zoom" onclick="exitZoom()">✕ Close Zoom</button>
<div class="counter"><span id="current-idx">1</span> / <?= count($image_list) ?></div>

<div id="viewer"></div>
<div id="filmstrip"></div>

<script>
    const images = <?php echo json_encode($image_list); ?>;
    const total = images.length;
    let currentIndex = 0;
    const viewer = document.getElementById('viewer');
    const filmstrip = document.getElementById('filmstrip');
    const counterText = document.getElementById('current-idx');

    // Zoom & Pan state
    let zoomMode = false;
    let zoomScale = 1;
    let panX = 0;
    let panY = 0;
    let initialFitScale = 1;
    let isDragging = false;
    let hasMoved = false;
    let lastX = 0;
    let lastY = 0;
    let initialPinchDist = 0;
    let initialPinchScale = 1;
    let touchMoved = false;

    // Optional TOC data (1-based pages)
    const tocData = <?php echo json_encode($toc); ?>;

    function init() {
        images.forEach((_, i) => {
            const slot = document.createElement('div');
            slot.className = 'thumb-slot';
            slot.id = `thumb-slot-${i}`;
            slot.innerHTML = `<span>${i + 1}</span>`;
            slot.onclick = () => showImage(i);
            filmstrip.appendChild(slot);
        });
        showImage(0);

        if (tocData && tocData.length > 0) {
            initTocUI();
        }
    }

    function captureThumb(img, index) {
        const slot = document.getElementById(`thumb-slot-${index}`);
        if (slot.querySelector('img')) return;
        const canvas = document.createElement('canvas');
        const ctx = canvas.getContext('2d');
        const scale = 80 / img.naturalHeight;
        canvas.width = img.naturalWidth * scale;
        canvas.height = 80;
        ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
        const thumbImg = document.createElement('img');
        thumbImg.src = canvas.toDataURL('image/jpeg', 0.6);
        slot.innerHTML = '';
        slot.appendChild(thumbImg);
    }

    // === NEW ZOOM SYSTEM (pinch + wheel + drag + tap/click to toggle) ===

    function updateImageTransform(img) {
        if (!img) return;
        const transform = `translate(-50%, -50%) translate(${panX}px, ${panY}px) scale(${zoomScale})`;
        img.style.transform = transform;
    }

    function clampPan(img) {
        if (!img || !img.naturalWidth || zoomScale <= 0) return;
        const vRect = viewer.getBoundingClientRect();
        const scaledW = img.naturalWidth * zoomScale;
        const scaledH = img.naturalHeight * zoomScale;
        const maxPanX = Math.max(0, (scaledW - vRect.width) / 2);
        const maxPanY = Math.max(0, (scaledH - vRect.height) / 2);
        panX = Math.max(-maxPanX, Math.min(maxPanX, panX));
        panY = Math.max(-maxPanY, Math.min(maxPanY, panY));
    }

    function enterZoomMode() {
        const activeImg = document.querySelector('.slide.active');
        if (!activeImg) return;

        if (!activeImg.complete || activeImg.naturalWidth === 0) {
            activeImg.onload = () => enterZoomMode();
            return;
        }

        zoomMode = true;
        document.body.classList.add('is-zoomed');
        viewer.style.overflow = 'hidden';
        viewer.style.touchAction = 'none';

        const natW = activeImg.naturalWidth;
        const natH = activeImg.naturalHeight;
        const vRect = viewer.getBoundingClientRect();

        initialFitScale = Math.min(vRect.width / natW, vRect.height / natH);
        zoomScale = initialFitScale;
        panX = 0;
        panY = 0;

        activeImg.style.position = 'absolute';
        activeImg.style.left = '50%';
        activeImg.style.top = '50%';
        activeImg.style.width = natW + 'px';
        activeImg.style.height = natH + 'px';
        activeImg.style.maxWidth = 'none';
        activeImg.style.maxHeight = 'none';
        activeImg.style.objectFit = 'none';
        activeImg.style.transformOrigin = 'center center';
        activeImg.style.willChange = 'transform';
        activeImg.style.cursor = 'grab';

        updateImageTransform(activeImg);
    }

    function exitZoomMode() {
        zoomMode = false;
        document.body.classList.remove('is-zoomed');
        viewer.style.overflow = 'auto';
        viewer.style.touchAction = 'pan-x pan-y pinch-zoom';

        const activeImg = document.querySelector('.slide.active');
        if (activeImg) {
            activeImg.style.transform = '';
            activeImg.style.position = '';
            activeImg.style.left = '';
            activeImg.style.top = '';
            activeImg.style.width = '';
            activeImg.style.height = '';
            activeImg.style.maxWidth = '';
            activeImg.style.maxHeight = '';
            activeImg.style.objectFit = '';
            activeImg.style.transformOrigin = '';
            activeImg.style.willChange = '';
            activeImg.style.cursor = 'zoom-in';
        }

        zoomScale = 1;
        panX = 0;
        panY = 0;
        initialFitScale = 1;
        isDragging = false;
        hasMoved = false;
        initialPinchDist = 0;
        touchMoved = false;
    }

    function exitZoom() {
        if (zoomMode) {
            exitZoomMode();
        }
    }

    function showImage(index) {
        if (index < 0) index = total - 1;
        if (index >= total) index = 0;
        currentIndex = index;

        exitZoom();

        const buffer = 2;
        const keep = [];
        for (let i = -buffer; i <= buffer; i++) keep.push((index + i + total) % total);

        viewer.querySelectorAll('.slide').forEach(img => {
            if (!keep.includes(parseInt(img.dataset.index))) img.remove();
            else img.classList.remove('active');
        });

        keep.forEach(idx => {
            let imgTag = document.querySelector(`.slide[data-index="${idx}"]`);
            if (!imgTag) {
                imgTag = document.createElement('img');
                imgTag.crossOrigin = "anonymous";
                imgTag.src = images[idx];
                imgTag.className = 'slide';
                imgTag.dataset.index = idx;
                imgTag.onload = () => captureThumb(imgTag, idx);
                viewer.appendChild(imgTag);
            }
            if (idx === currentIndex) imgTag.classList.add('active');
        });

        counterText.innerText = currentIndex + 1;
        document.querySelectorAll('.thumb-slot').forEach(s => s.classList.remove('active'));
        const activeSlot = document.getElementById(`thumb-slot-${index}`);
        activeSlot.classList.add('active');
        activeSlot.scrollIntoView({ behavior: 'smooth', inline: 'center' });
    }

    // Swiping (disabled in zoom via class check)
    let touchstartX = 0;
    viewer.addEventListener('touchstart', e => {
        if (document.body.classList.contains('is-zoomed')) return;
        touchstartX = e.changedTouches[0].screenX;
    }, {passive: true});

    viewer.addEventListener('touchend', e => {
        if (document.body.classList.contains('is-zoomed')) return;
        let touchendX = e.changedTouches[0].screenX;
        if (touchendX < touchstartX - 60) showImage(currentIndex + 1);
        if (touchendX > touchstartX + 60) showImage(currentIndex - 1);
    }, {passive: true});

    // Zoom-mode touch handlers
    viewer.addEventListener('touchstart', e => {
        if (!zoomMode) return;
        touchMoved = false;
        if (e.touches.length === 1) {
            lastX = e.touches[0].clientX;
            lastY = e.touches[0].clientY;
        } else if (e.touches.length === 2) {
            initialPinchDist = Math.hypot(
                e.touches[0].clientX - e.touches[1].clientX,
                e.touches[0].clientY - e.touches[1].clientY
            );
            initialPinchScale = zoomScale;
        }
        e.preventDefault();
    }, {passive: false});

    viewer.addEventListener('touchmove', e => {
        if (!zoomMode) return;
        const activeImg = document.querySelector('.slide.active');
        if (!activeImg) return;

        if (e.touches.length === 1) {
            const dx = e.touches[0].clientX - lastX;
            const dy = e.touches[0].clientY - lastY;
            if (Math.abs(dx) > 3 || Math.abs(dy) > 3) touchMoved = true;
            panX += dx;
            panY += dy;
            lastX = e.touches[0].clientX;
            lastY = e.touches[0].clientY;
            clampPan(activeImg);
            updateImageTransform(activeImg);
        } else if (e.touches.length === 2) {
            const currentDist = Math.hypot(
                e.touches[0].clientX - e.touches[1].clientX,
                e.touches[0].clientY - e.touches[1].clientY
            );
            if (initialPinchDist > 10) {
                const scaleFactor = currentDist / initialPinchDist;
                zoomScale = initialPinchScale * scaleFactor;
                zoomScale = Math.max(0.2, Math.min(zoomScale, 8));
                if (Math.abs(scaleFactor - 1) > 0.01) touchMoved = true;
                clampPan(activeImg);
                updateImageTransform(activeImg);
            }
        }
        e.preventDefault();
    }, {passive: false});

    viewer.addEventListener('touchend', e => {
        if (!zoomMode) return;
        if (e.touches.length === 0) {
            if (!touchMoved) {
                setTimeout(() => { if (zoomMode) exitZoomMode(); }, 60);
            }
            initialPinchDist = 0;
            touchMoved = false;
        } else if (e.touches.length === 1) {
            initialPinchDist = 0;
        }
    }, {passive: false});

    // Desktop mouse support
    viewer.addEventListener('mousedown', e => {
        if (!zoomMode) return;
        isDragging = true;
        hasMoved = false;
        lastX = e.clientX;
        lastY = e.clientY;
        viewer.style.cursor = 'grabbing';
        e.preventDefault();
    });

    viewer.addEventListener('mousemove', e => {
        if (!zoomMode || !isDragging) return;
        const dx = e.clientX - lastX;
        const dy = e.clientY - lastY;
        if (Math.abs(dx) > 2 || Math.abs(dy) > 2) hasMoved = true;
        panX += dx;
        panY += dy;
        lastX = e.clientX;
        lastY = e.clientY;
        const activeImg = document.querySelector('.slide.active');
        if (activeImg) {
            clampPan(activeImg);
            updateImageTransform(activeImg);
        }
        e.preventDefault();
    });

    viewer.addEventListener('mouseup', e => {
        if (!zoomMode) return;
        isDragging = false;
        const activeImg = document.querySelector('.slide.active');
        if (activeImg) {
            activeImg.style.cursor = (zoomScale > initialFitScale * 1.02) ? 'grab' : 'default';
        }
        viewer.style.cursor = '';
    });

    // Click to enter/exit zoom
    viewer.addEventListener('click', e => {
        const activeImg = document.querySelector('.slide.active');
        if (!activeImg) return;

        if (!zoomMode) {
            enterZoomMode();
        } else if (!hasMoved && !isDragging) {
            exitZoomMode();
        }
        hasMoved = false;
    });

    // Wheel zoom with focal point
    viewer.addEventListener('wheel', e => {
        if (!zoomMode) return;
        e.preventDefault();
        const activeImg = document.querySelector('.slide.active');
        if (!activeImg) return;

        const oldScale = zoomScale;
        const factor = (e.deltaY < 0) ? 1.18 : 0.86;
        let newScale = oldScale * factor;
        newScale = Math.max(0.2, Math.min(newScale, 8));
        if (newScale === oldScale) return;

        const rect = viewer.getBoundingClientRect();
        const mouseX = e.clientX - rect.left;
        const mouseY = e.clientY - rect.top;
        const imgCenterX = rect.width / 2 + panX;
        const imgCenterY = rect.height / 2 + panY;
        const offX = mouseX - imgCenterX;
        const offY = mouseY - imgCenterY;
        const scaleRatio = newScale / oldScale;

        panX = panX - offX * (scaleRatio - 1);
        panY = panY - offY * (scaleRatio - 1);

        zoomScale = newScale;
        clampPan(activeImg);
        updateImageTransform(activeImg);
    }, {passive: false});

    // Keyboard
    document.addEventListener('keydown', e => {
        if (e.key === "ArrowRight") showImage(currentIndex + 1);
        if (e.key === "ArrowLeft")  showImage(currentIndex - 1);
        if (e.key === "Escape")     exitZoom();
    });

    // TOC UI
    function initTocUI() {
        const tocBtn = document.createElement('button');
        tocBtn.id = 'toc-btn';
        tocBtn.innerHTML = '☰ TOC';
        tocBtn.title = 'Jump to section';
        document.body.appendChild(tocBtn);

        const overlay = document.createElement('div');
        overlay.id = 'toc-overlay';
        overlay.className = 'toc-overlay';
        overlay.innerHTML = `
            <div class="toc-panel">
                <div class="toc-header">
                    <span>Table of Contents</span>
                    <button class="toc-close" aria-label="Close">✕</button>
                </div>
                <div class="toc-list" id="toc-list"></div>
            </div>
        `;
        document.body.appendChild(overlay);

        const listEl = overlay.querySelector('#toc-list');

        tocData.forEach(entry => {
            const item = document.createElement('div');
            item.className = 'toc-item';
            item.innerHTML = `
                <div class="toc-page">${entry.page}</div>
                <div class="toc-title">${entry.title}</div>
            `;
            item.onclick = () => {
                overlay.style.display = 'none';
                showImage(entry.page - 1);
            };
            listEl.appendChild(item);
        });

        tocBtn.onclick = () => { overlay.style.display = 'flex'; };
        overlay.querySelector('.toc-close').onclick = () => { overlay.style.display = 'none'; };
        overlay.onclick = (ev) => { if (ev.target === overlay) overlay.style.display = 'none'; };
    }

    init();
</script>
</body>
</html>
