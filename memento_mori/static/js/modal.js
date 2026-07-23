// memento_mori/static/js/modal.js
document.addEventListener('DOMContentLoaded', function () {
    // Get DOM elements
    const postModal = document.getElementById('postModal');
    const closeModalBtn = document.getElementById('closeModal');
    const modalPrev = document.getElementById('modalPrev');
    const modalNext = document.getElementById('modalNext');
    const postMedia = document.getElementById('postMedia');
    const postCaption = document.getElementById('postCaption');
    const postStats = document.getElementById('postStats');
    const postDate = document.getElementById('postDate');
    const postPlace = document.getElementById('postPlace');
    const postUsername = document.getElementById('postUsername');

    // Global variables to track current post and indexes
    let currentPostIndex = -1;
    let currentSlideIndex = 0;
    let postIndexToTimestamp = {}; // Map post index to timestamp
    let modalOpen = false;          // Whether the dialog is open (for the focus trap)
    let lastFocused = null;         // Element to restore focus to on close
    let postMap = null;             // Lazily-created Leaflet map for the post location
    let postMapMarker = null;

    // Hide the rest of the page from tab order + assistive tech while the
    // dialog is open (the dialog is a body-level sibling of these landmarks)
    function setBackgroundInert(on) {
        ['header', 'main', 'footer'].forEach(function (sel) {
            const el = document.querySelector(sel);
            if (!el) return;
            if (on) {
                el.setAttribute('inert', '');
                el.setAttribute('aria-hidden', 'true');
            } else {
                el.removeAttribute('inert');
                el.removeAttribute('aria-hidden');
            }
        });
    }

    // Keep Tab focus inside the open modal
    function trapModalFocus(e) {
        if (!modalOpen || e.key !== 'Tab') return;
        const focusable = Array.prototype.filter.call(
            postModal.querySelectorAll('button, a[href], video, [tabindex]:not([tabindex="-1"])'),
            el => el.offsetParent !== null
        );
        if (!focusable.length) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (e.shiftKey && document.activeElement === first) {
            e.preventDefault();
            last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
            e.preventDefault();
            first.focus();
        }
    }

    // Initialize by creating mapping and attaching listeners
    function initialize() {
        // Create a mapping from post index to timestamp
        Object.entries(window.postData).forEach(([timestamp, post]) => {
            postIndexToTimestamp[post.i] = timestamp;
        });

        // Attach click listeners to grid items
        attachGridItemListeners();
    }

    // Sorting lives in posts-grid.js.
    // It used to live here, back when the server shipped every tile and
    // sorting meant reordering DOM nodes that were already present. The posts
    // grid is now progressive — only a first chunk is in the DOM — so sorting
    // has to reorder the *data* and rebuild, which is the grid builder's job.
    // Doing it in both places would double-handle every click on .sort-link.

    // One delegated click listener covers every .grid-item tile (thousands
    // on the larger pages) — much cheaper than binding each tile, and
    // reordering/sorting tiles needs no rebinding.
    let gridListenerBound = false;
    function attachGridItemListeners() {
        if (gridListenerBound) return;
        gridListenerBound = true;
        document.addEventListener('click', function (e) {
            const item = e.target.closest('.grid-item');
            if (!item) return;
            // Flickr tiles share the grid-item styling but belong to the
            // flickr viewer (flickr-viewer.js's own delegated listener)
            if (item.classList.contains('flickr-tile')) return;
            // On the timeline page tiles are links (no-JS fallback);
            // open the modal in place instead of navigating away
            if (item.tagName === 'A') {
                e.preventDefault();
            }
            const postIndex = parseInt(item.getAttribute('data-index'));
            openModal(postIndex);
        });
    }

    // Open the modal with the selected post
    function openModal(index, imageIndex = 0) {
        currentPostIndex = index;

        // Remember what to restore focus to when the modal closes (only the
        // opening trigger, not the prev/next buttons when navigating posts)
        if (!modalOpen) {
            lastFocused = document.activeElement;
        }

        // Store the current scroll position before opening the modal
        const scrollPosition = window.pageYOffset || document.documentElement.scrollTop;

        // Get the timestamp using the post_index mapping
        const timestamp = postIndexToTimestamp[index];

        // Get the post data using the timestamp
        const post = window.postData[timestamp];

        // Show the modal first (important for correct dimensions)
        postModal.style.display = 'block';
        document.body.style.overflow = 'hidden'; // Prevent scrolling

        // Store the scroll position as a data attribute on the modal
        postModal.setAttribute('data-scroll-position', scrollPosition);

        // Update modal content
        updateModalContent(post, imageIndex);

        // Update URL with post ID and image index
        updateUrlWithPostInfo(timestamp, imageIndex);

        // Dialog is now open: hide the background and move focus inside
        modalOpen = true;
        setBackgroundInert(true);
        closeModalBtn.focus();

        // For mobile devices, ensure content is visible and properly sized
        if (window.innerWidth <= 768) {
            // Don't scroll to top on mobile as it causes the issue
            // Instead, just ensure the modal is properly positioned
            postModal.scrollTop = 0;

            // Force layout recalculation with a longer timeout
            setTimeout(() => {
                const mediaContainer = document.querySelector('.media-container');
                const postMediaEl = document.getElementById('postMedia');

                // Ensure post-media has explicit height
                if (postMediaEl) {
                    postMediaEl.style.height = '50vh';
                    postMediaEl.style.minHeight = '300px';
                }

                // Ensure media-container has explicit height
                if (mediaContainer) {
                    mediaContainer.style.height = '100%';
                    mediaContainer.style.display = 'flex';

                    // Force reflow
                    void mediaContainer.offsetHeight;
                }

                // Reset any active slides to ensure they're visible
                const activeSlides = document.querySelectorAll('.media-slide.active');
                activeSlides.forEach(slide => {
                    slide.style.opacity = '0';
                    void slide.offsetHeight; // Force reflow
                    slide.style.opacity = '1';

                    // Make sure images have height
                    const img = slide.querySelector('img');
                    if (img) {
                        img.style.maxHeight = '100%';
                        img.style.width = 'auto';
                        img.style.height = 'auto';
                    }
                });
            }, 50); // Increase timeout for more reliability
        }
    }

    // Function to update the URL with post and image information
    function updateUrlWithPostInfo(timestamp, imageIndex) {
        // Create a new URL object based on the current URL
        const url = new URL(window.location.href);

        // Set the post parameter to the timestamp
        url.searchParams.set('post', timestamp);

        // Only add the image parameter if it's not the first image
        if (imageIndex > 0) {
            url.searchParams.set('image', imageIndex);
        } else {
            url.searchParams.delete('image');
        }

        // Update the browser history without reloading the page
        window.history.pushState({}, '', url);
    }
    // Poster (first-frame thumbnail) for the video at media index i, if any.
    function videoPoster(post, index) {
        return (post && post.vp && post.vp[index]) || null;
    }

    // Creates the appropriate media element (video or image) based on the file type
    function createMediaElement(mediaUrl, poster) {
        // Check if the media is a video based on file extension
        if (mediaUrl.endsWith('.mp4') || mediaUrl.endsWith('.mov') ||
            mediaUrl.endsWith('.avi') || mediaUrl.endsWith('.webm')) {

            // Create video element (no autoplay — the viewer presses play)
            const video = document.createElement('video');
            video.src = mediaUrl;
            video.controls = true;
            video.autoplay = false;
            video.loop = true;
            video.muted = false;
            video.playsInline = true;
            video.preload = 'metadata';
            // Show the first-frame still instead of a blank box until play.
            if (poster) video.poster = poster;
            video.alt = 'Instagram video post';

            return video;
        } else {
            // Create image element
            const img = document.createElement('img');

            // Check if there's a WebP version available for non-WebP images
            if (!mediaUrl.endsWith('.webp') &&
                (mediaUrl.endsWith('.jpg') || mediaUrl.endsWith('.jpeg') ||
                    mediaUrl.endsWith('.png') || mediaUrl.endsWith('.gif'))) {

                // Try to use WebP version if it exists
                const webpUrl = mediaUrl.replace(/\.(jpg|jpeg|png|gif)$/i, '.webp');

                // Set up error handling to fall back to original if WebP doesn't exist
                img.onerror = function () {
                    this.onerror = null; // Prevent infinite loop
                    this.src = mediaUrl; // Fall back to original
                };

                img.src = webpUrl;
            } else {
                img.src = mediaUrl;
            }

            img.alt = 'Instagram post';

            return img;
        }
    }
    // Update modal content with the post data
    function updateModalContent(post, initialImageIndex = 0) {
        // Clear previous content
        postMedia.innerHTML = '';
        postCaption.innerHTML = '';
        postStats.innerHTML = '';

        // Create media container for the slides
        const mediaContainer = document.createElement('div');
        mediaContainer.className = 'media-container';

        // Check if the post has multiple media
        if (post.m && post.m.length > 1) {  // Changed from media
            // Create slides for each media item
            post.m.forEach((mediaUrl, index) => {  // Changed from media
                const slide = document.createElement('div');
                slide.className = `media-slide ${index === initialImageIndex ? 'active' : ''}`;

                // Create and add the appropriate media element
                const mediaElement = createMediaElement(mediaUrl, videoPoster(post, index));
                slide.appendChild(mediaElement);

                mediaContainer.appendChild(slide);
            });

            // Add navigation buttons for slideshow
            const prevBtn = document.createElement('button');
            prevBtn.type = 'button';
            prevBtn.className = 'slideshow-nav slideshow-prev icon-button';
            prevBtn.setAttribute('aria-label', 'Previous photo');
            prevBtn.innerHTML = '❮';
            prevBtn.addEventListener('click', function (e) {
                e.stopPropagation();
                navigateSlideshow(-1);
            });

            const nextBtn = document.createElement('button');
            nextBtn.type = 'button';
            nextBtn.className = 'slideshow-nav slideshow-next icon-button';
            nextBtn.setAttribute('aria-label', 'Next photo');
            nextBtn.innerHTML = '❯';
            nextBtn.addEventListener('click', function (e) {
                e.stopPropagation();
                navigateSlideshow(1);
            });

            // Add indicator dots
            const indicator = document.createElement('div');
            indicator.className = 'slideshow-indicator';

            for (let i = 0; i < post.m.length; i++) {
                const dot = document.createElement('button');
                dot.type = 'button';
                dot.className = `slideshow-dot icon-button ${i === initialImageIndex ? 'active' : ''}`;
                dot.setAttribute('data-index', i);
                dot.setAttribute('aria-label', 'Go to photo ' + (i + 1));
                dot.addEventListener('click', function (e) {
                    e.stopPropagation();
                    const index = parseInt(this.getAttribute('data-index'));
                    showSlide(index);
                });
                indicator.appendChild(dot);
            }

            mediaContainer.appendChild(prevBtn);
            mediaContainer.appendChild(nextBtn);
            mediaContainer.appendChild(indicator);

            // Set the current slide index to the initial image index
            currentSlideIndex = initialImageIndex;
        } else {
            // Single media post
            const slide = document.createElement('div');
            slide.className = 'media-slide active';

            // Create and add the appropriate media element
            const mediaElement = createMediaElement(post.m[0], videoPoster(post, 0));
            slide.appendChild(mediaElement);

            mediaContainer.appendChild(slide);
        }

        postMedia.appendChild(mediaContainer);

        // Set tagged place under the username, like Instagram does
        if (postPlace) {
            postPlace.textContent = post.pl || '';
            postPlace.style.display = post.pl ? 'block' : 'none';
        }

        // Set post caption (encoding fixed lazily on first open, memoized)
        if (post.tt) {
            if (!post.ttFixed) {
                post.tt = fixEncodingIssues(post.tt);
                post.ttFixed = true;
            }
            postCaption.innerHTML = post.tt.replace(/\n/g, '<br>');
        } else {
            postCaption.innerHTML = '';
        }

        // Set post stats
        if (post.im) {
            const impressionsDiv = document.createElement('div');
            impressionsDiv.className = 'post-stat';
            impressionsDiv.innerHTML = `
                <span class="post-stat-icon">👁️</span>
                <span>${post.im} views</span>
            `;
            postStats.appendChild(impressionsDiv);
        }

        if (post.l) {
            const likesDiv = document.createElement('div');
            likesDiv.className = 'post-stat';
            likesDiv.innerHTML = `
                <span class="post-stat-icon">♥</span>
                <span>${post.l}</span>
            `;
            postStats.appendChild(likesDiv);
        }

        if (post.c) {
            const commentsDiv = document.createElement('div');
            commentsDiv.className = 'post-stat';
            commentsDiv.innerHTML = `
                <span class="post-stat-icon">💬</span>
                <span>${post.c} comments</span>
            `;
            postStats.appendChild(commentsDiv);
        }

        // Small location map (only for posts that carry coordinates)
        updatePostMap(post);

        // Set post date
        postDate.textContent = post.d;

        // Show/hide stats container based on whether there are any stats
        postStats.style.display = postStats.children.length > 0 ? 'flex' : 'none';
    }

    // Show a small Leaflet locator map for the post's coordinates (~73% of
    // posts have them); hide the container for posts without coordinates.
    // The map instance is created once and reused across posts.
    function updatePostMap(post) {
        const mapEl = document.getElementById('postMap');
        if (!mapEl) return;

        const la = parseFloat(post.la);
        const lo = parseFloat(post.lo);
        if (!isFinite(la) || !isFinite(lo) || typeof L === 'undefined') {
            mapEl.style.display = 'none';
            return;
        }

        mapEl.style.display = 'block';

        if (!postMap) {
            // scrollWheelZoom off so the page still scrolls over the map;
            // fadeAnimation off avoids tiles stuck at opacity 0 (Leaflet gotcha).
            postMap = L.map(mapEl, { scrollWheelZoom: false, fadeAnimation: false });
            L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
                maxZoom: 19,
                attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
            }).addTo(postMap);
        }

        const latlng = [la, lo];
        postMap.setView(latlng, 14);
        if (postMapMarker) {
            postMapMarker.setLatLng(latlng);
        } else {
            postMapMarker = L.marker(latlng).addTo(postMap);
        }

        // The modal was just shown; let layout settle, then have Leaflet
        // re-measure (else tiles render into a 0-size box).
        setTimeout(function () {
            postMap.invalidateSize();
            postMap.setView(latlng, 14);
        }, 60);
    }

    // Navigate between slides in a multi-media post
    function navigateSlideshow(direction) {
        const slides = document.querySelectorAll('.media-slide');
        const dots = document.querySelectorAll('.slideshow-dot');
        let activeIndex = 0;

        // Find the currently active slide
        slides.forEach((slide, index) => {
            if (slide.classList.contains('active')) {
                activeIndex = index;
            }
        });

        // Pause any videos in the current slide
        const currentVideo = slides[activeIndex].querySelector('video');
        if (currentVideo) {
            currentVideo.pause();
        }

        // Calculate the new index
        let newIndex = activeIndex + direction;
        if (newIndex < 0) newIndex = slides.length - 1;
        if (newIndex >= slides.length) newIndex = 0;

        // Update slides and dots
        showSlide(newIndex);
    }

    // Show a specific slide
    function showSlide(index) {
        const slides = document.querySelectorAll('.media-slide');
        const dots = document.querySelectorAll('.slideshow-dot');

        // Pause all videos before changing slides
        slides.forEach(slide => {
            const video = slide.querySelector('video');
            if (video) {
                video.pause();
            }
        });

        // Remove active class from all slides and dots
        slides.forEach(slide => slide.classList.remove('active'));
        if (dots.length > 0) {
            dots.forEach(dot => dot.classList.remove('active'));
            dots[index].classList.add('active');
        }

        // Add active class to the selected slide
        slides[index].classList.add('active');

        // Update current slide index
        currentSlideIndex = index;

        // Update URL with the new image index
        const timestamp = postIndexToTimestamp[currentPostIndex];
        updateUrlWithPostInfo(timestamp, index);
    }

    // Navigate between posts (next/prev buttons in modal)
    function navigatePost(direction) {
        // Pause all videos in the current post
        const videos = document.querySelectorAll('.media-slide video');
        videos.forEach(video => {
            if (video) {
                video.pause();
            }
        });

        // Prefer an explicit order published by a progressive grid: on
        // posts.html only a first chunk of tiles is in the DOM, so walking
        // .grid-item would stop navigation at the last appended tile.
        // posts-grid.js publishes every post index in the current sort order.
        //
        // The DOM walk remains the fallback for pages that render their own
        // tile set and have no such list — the timeline, cities and map.
        // Flickr tiles share the .grid-item class but carry data-id instead
        // of data-index, so they parse to NaN — drop them or they become
        // dead stops in the post carousel on any page that mixes sources.
        let gridIndexes;
        if (Array.isArray(window.mmPostsOrder) && window.mmPostsOrder.length) {
            gridIndexes = window.mmPostsOrder;
        } else {
            gridIndexes = Array.from(document.querySelectorAll('.grid-item'))
                .map(item => parseInt(item.getAttribute('data-index')))
                .filter(index => !isNaN(index));
        }

        // Find the position of the current post in the sorted grid
        const currentPosition = gridIndexes.indexOf(currentPostIndex);

        if (currentPosition === -1) {
            // No grid on this page (e.g. a ?post= deep link on the map page
            // before a selection) — nothing to navigate between.
            return;
        }

        // Calculate new position with wraparound
        let newPosition = (currentPosition + direction + gridIndexes.length) % gridIndexes.length;

        // Get the new post index from the grid's current order
        const newPostIndex = gridIndexes[newPosition];

        // Open the new post
        openModal(newPostIndex);
    }

    // Close the modal
    function closeModal() {
        // Pause all videos before closing the modal
        const videos = document.querySelectorAll('.media-slide video');
        videos.forEach(video => {
            if (video) {
                video.pause();
            }
        });

        // Store the current scroll position before closing the modal
        const scrollPosition = window.pageYOffset || document.documentElement.scrollTop;

        postModal.style.display = 'none';
        document.body.style.overflow = 'auto'; // Re-enable scrolling

        // Dialog closed: restore the background and return focus to the trigger
        modalOpen = false;
        setBackgroundInert(false);

        // Remove post and image parameters from URL
        const url = new URL(window.location.href);
        url.searchParams.delete('post');
        url.searchParams.delete('image');
        window.history.pushState({}, '', url);

        // Restore the scroll position after a short delay
        setTimeout(() => {
            window.scrollTo({
                top: scrollPosition,
                behavior: 'auto' // Use 'auto' instead of 'smooth' to prevent visible scrolling
            });
            if (lastFocused && typeof lastFocused.focus === 'function') {
                // Restore focus without scrolling. Safari/WebKit does not focus an <a>
                // when it is clicked, so lastFocused is often an ancestor such as
                // <main tabindex="-1"> — and focusing that scrolls it into view,
                // throwing the reader from wherever they were back to the top of
                // the page. Chromium focuses the link itself, which is why this
                // only ever showed up in Safari.
                lastFocused.focus({ preventScroll: true });
            }
        }, 10);
    }

    // Expose an open-by-index hook so other views (e.g. "On this day") can
    // open the modal in place without duplicating the tile-click plumbing.
    window.mmOpenPost = openModal;

    // Event listeners for modal navigation
    closeModalBtn.addEventListener('click', closeModal);
    modalPrev.addEventListener('click', function (e) {
        e.stopPropagation();
        navigatePost(-1);
    });
    modalNext.addEventListener('click', function (e) {
        e.stopPropagation();
        navigatePost(1);
    });

    // Close modal when clicking outside of content
    postModal.addEventListener('click', function (e) {
        if (e.target === postModal) {
            closeModal();
        }
    });

    // Keyboard navigation
    document.addEventListener('keydown', function (e) {
        if (postModal.style.display === 'block') {
            if (e.key === 'Escape') {
                closeModal();
            } else if (e.key === 'Tab') {
                trapModalFocus(e);
            } else if (e.key === 'ArrowLeft') {
                navigatePost(-1);
            } else if (e.key === 'ArrowRight') {
                navigatePost(1);
            }
        }
    });

    // Initialize the modal functionality
    if (typeof window.postData !== 'undefined') {
        initialize();

        // Check if URL has post and image parameters
        const urlParams = new URLSearchParams(window.location.search);
        const postTimestamp = urlParams.get('post');
        const imageIndex = parseInt(urlParams.get('image') || '0');

        if (postTimestamp && window.postData[postTimestamp]) {
            // Find the post index from the timestamp
            let postIndex = -1;
            Object.entries(postIndexToTimestamp).forEach(([index, timestamp]) => {
                if (timestamp === postTimestamp) {
                    postIndex = parseInt(index);
                }
            });

            if (postIndex >= 0) {
                // Open the modal with the specified post and image
                setTimeout(() => {
                    openModal(postIndex, imageIndex);
                }, 500); // Delay to ensure everything is loaded
            }
        }
    } else {
        console.error('Post data not available');
    }
});





/**
 * Fixes common Unicode encoding issues in text
 * @param {string} text - The text to fix
 * @return {string} - The fixed text
 */
function fixEncodingIssues(text) {
    if (!text) return text;
    
    // Common replacements for incorrectly encoded characters
    const replacements = [
      // Fix smart quotes and apostrophes
      { pattern: /â\u0080\u0099/g, replacement: "\u2019" },  // Right single quote/apostrophe
      { pattern: /â\u0080\u009c/g, replacement: "\u201C" },  // Left double quote
      { pattern: /â\u0080\u009d/g, replacement: "\u201D" },  // Right double quote
      { pattern: /â\u0080\u0098/g, replacement: "\u2018" },  // Left single quote
      
      // Fix dashes and ellipsis
      { pattern: /â\u0080\u0093/g, replacement: "\u2013" },  // En dash
      { pattern: /â\u0080\u0094/g, replacement: "\u2014" },  // Em dash
      { pattern: /â\u0080¦/g,   replacement: "\u2026" },      // Ellipsis
      
      // Remove non-breaking space indicator
      { pattern: /Â/g, replacement: "" },
      
      // Fix fractions
      { pattern: /Â½/g, replacement: "\u00BD" },             // Half fraction
  
      // Fix bullet point
      { pattern: /â€¢/g, replacement: "•" },
  
      // Fix common mis-encoded accented characters
      { pattern: /Ã©/g, replacement: "é" },
      { pattern: /Ã¨/g, replacement: "è" },
      { pattern: /Ã¢/g, replacement: "â" },
      { pattern: /Ãª/g, replacement: "ê" },
      { pattern: /Ã«/g, replacement: "ë" },
      { pattern: /Ã®/g, replacement: "î" },
      { pattern: /Ã¯/g, replacement: "ï" },
      { pattern: /Ã´/g, replacement: "ô" },
      { pattern: /Ã¶/g, replacement: "ö" },
      { pattern: /Ã¹/g, replacement: "ù" },
      { pattern: /Ãº/g, replacement: "ú" },
      { pattern: /Ã¼/g, replacement: "ü" },
      { pattern: /Ã§/g, replacement: "ç" }
    ];
    
    // Apply all replacements
    let fixedText = text;
    for (const { pattern, replacement } of replacements) {
      fixedText = fixedText.replace(pattern, replacement);
    }
  
    return fixedText;
  }
    
  // Captions are fixed lazily (and memoized) when a post is opened — see
  // updateModalContent — instead of an eager pass over every post at load.
  
