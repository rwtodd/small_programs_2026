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
            /* allow-pan allows browser to handle panning/pinch when zoomed */
            touch-action: pan-x pan-y pinch-zoom; 
            -webkit-overflow-scrolling: touch;
        }

        .slide { 
            max-width: 100%; max-height: 100%; 
            object-fit: contain; display: none; 
            cursor: zoom-in;
        }
        .slide.active { display: block; }

        /* Full-Size Mode */
        .slide.zoomed { 
            max-width: none; max-height: none; 
            object-fit: none; /* Render at 1:1 natural size */
            cursor: zoom-out;
            align-self: flex-start; /* Prevents top cutoff in flex container */
        }

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

        /* State Changes */
        body.is-zoomed #viewer { bottom: 0; } /* Expand viewer to full screen */
        body.is-zoomed #filmstrip, body.is-zoomed .counter { display: none; }
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

    function exitZoom() {
        const activeImg = document.querySelector('.slide.active');
        if (activeImg) activeImg.classList.remove('zoomed');
        document.body.classList.remove('is-zoomed');
        viewer.scrollTo(0,0);
    }

    function showImage(index) {
        if (index < 0) index = total - 1;
        if (index >= total) index = 0;
        currentIndex = index;
        
        exitZoom(); // Reset zoom state when switching images

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
                imgTag.onclick = () => {
                    if (!imgTag.classList.contains('zoomed')) {
                        imgTag.classList.add('zoomed');
                        document.body.classList.add('is-zoomed');
                    }
                };
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

    // Swiping (Only active when NOT zoomed)
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

    // Keyboard
    document.addEventListener('keydown', e => {
        if (e.key === "ArrowRight") showImage(currentIndex + 1);
        if (e.key === "ArrowLeft")  showImage(currentIndex - 1);
        if (e.key === "Escape")     exitZoom();
    });

    init();
</script>
</body>
</html>
