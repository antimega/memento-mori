// Stories viewer functionality
document.addEventListener('DOMContentLoaded', function() {
    // Story viewer elements
    const storyViewer = document.getElementById('storyViewer');
    const storyMedia = document.getElementById('storyMedia');
    const storyCaption = document.getElementById('storyCaption');
    const storyDate = document.getElementById('storyDate');
    const storyClose = document.getElementById('storyClose');
    const storyPrev = document.getElementById('storyPrev');
    const storyNext = document.getElementById('storyNext');
    const storyProgress = document.getElementById('storyProgress');
    
    // Story data and state
    let currentStoryIndex = 0;
    let storyItems = [];
    let autoProgressTimer = null;
    let isNavigating = false;
    const autoProgressDelay = 10000; // 10 seconds
    let storyOpen = false;           // Whether the viewer is open (focus trap)
    let lastFocused = null;          // Element to restore focus to on close
    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    // Hide the rest of the page from tab order + assistive tech while the
    // viewer is open (it is a body-level sibling of these landmarks)
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

    // Keep Tab focus inside the open story viewer
    function trapStoryFocus(e) {
        if (!storyOpen || e.key !== 'Tab') return;
        const focusable = Array.prototype.filter.call(
            storyViewer.querySelectorAll('button, a[href], video, [tabindex]:not([tabindex="-1"])'),
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
    
    // One delegated click listener covers every .story-item tile (thousands
    // on the larger pages) — much cheaper than binding each tile.
    const storyGridItems = document.querySelectorAll('.story-item');
    document.addEventListener('click', function(e) {
        const item = e.target.closest('.story-item');
        if (!item) return;
        // On the timeline page tiles are links (no-JS fallback);
        // open the story viewer in place instead of navigating away
        if (item.tagName === 'A') {
            e.preventDefault();
        }
        const storyIndex = parseInt(item.getAttribute('data-index'));
        openStory(storyIndex);
    });
    
    // Open a story by index
    function openStory(index) {
        // Get all story items in their current order
        storyItems = Array.from(document.querySelectorAll('.story-item'));
        currentStoryIndex = storyItems.findIndex(item => parseInt(item.getAttribute('data-index')) === index);

        if (currentStoryIndex === -1) return;

        // Remember what to restore focus to when the viewer closes
        if (!storyOpen) {
            lastFocused = document.activeElement;
        }

        // Show the story viewer
        storyViewer.style.display = 'flex';
        document.body.style.overflow = 'hidden'; // Prevent scrolling

        // Load the current story
        loadCurrentStory();

        // Viewer is now open: hide the background and move focus inside
        storyOpen = true;
        setBackgroundInert(true);
        storyClose.focus();

        // Update URL with story info
        const timestamp = storyItems[currentStoryIndex].getAttribute('data-timestamp');
        if (timestamp) {
            const url = new URL(window.location.href);
            url.searchParams.set('story', timestamp);
            window.history.pushState({}, '', url);
        }
    }
    
    // Load the current story content
    function loadCurrentStory() {
        if (currentStoryIndex < 0 || currentStoryIndex >= storyItems.length) return;
        
        // Clear any existing timer
        clearAutoProgressTimer();
        
        // Reset pause state when loading a new story
        if (isPaused) {
            isPaused = false;
            pauseIcon.style.display = 'block';
            playIcon.style.display = 'none';
            storyPause.setAttribute('aria-label', 'Pause');
            storyPause.setAttribute('aria-pressed', 'false');
        }
        
        // Reset progress bar
        storyProgress.style.width = '0%';
        
        // Clear previous media
        storyMedia.innerHTML = '';
        
        // Ensure the story media container has the correct class
        storyMedia.className = 'story-media-container';
        
        // Create a new slide
        const slide = document.createElement('div');
        slide.className = 'media-slide active';
        slide.style.opacity = '1';
        slide.style.transform = 'translateX(0)';
        
        // Load content into the slide
        loadStoryContent(slide, currentStoryIndex);
        
        // Add the slide to the container
        storyMedia.appendChild(slide);
    }
    
    // Start auto-progress timer with visual indicator
    function startAutoProgressTimer() {
        // Don't start timer if paused
        if (isPaused) {
            console.log('Not starting timer because story is paused');
            return;
        }
        
        console.log('Starting auto-progress timer with delay:', autoProgressDelay, 'ms');
        
        // Animate progress bar
        storyProgress.style.transition = `width ${autoProgressDelay}ms linear`;
        storyProgress.style.width = '100%';
        
        // Set timer for auto-progression
        autoProgressTimer = setTimeout(() => {
            console.log('Auto-progress timer completed, navigating to next story');
            navigateStory(1);
        }, autoProgressDelay);
    }
    
    // Clear auto-progress timer
    function clearAutoProgressTimer() {
        console.log('Clearing auto-progress timer');
        clearTimeout(autoProgressTimer);
        autoProgressTimer = null;
        
        // Also clear any video timer if it exists
        const videoElement = storyMedia.querySelector('video');
        if (videoElement && videoElement.videoTimer) {
            clearTimeout(videoElement.videoTimer);
            videoElement.videoTimer = null;
        }
        
        // Reset progress bar immediately
        storyProgress.style.transition = 'none';
        storyProgress.style.width = '0%';
        
        // Force a reflow to ensure the transition is reset
        storyProgress.offsetHeight;
    }
    
    // Helper function to load story content into a slide
    function loadStoryContent(slide, index) {
        const storyItem = storyItems[index];
        const timestamp = storyItem.getAttribute('data-timestamp');
        const storyData = window.storiesData[timestamp];
    
        if (!storyData) {
            isNavigating = false; // Reset navigation lock if we can't load content
            return;
        }
        
        // Update story date
        storyDate.textContent = storyData.d || '';
        
        // Create media element based on type
        const mediaUrl = storyData.m[0]; // Use first media item
        const isVideo = mediaUrl.endsWith('.mp4') || mediaUrl.endsWith('.mov') || 
                       mediaUrl.endsWith('.avi') || mediaUrl.endsWith('.webm');
        
        if (isVideo) {
            console.log('Loading video story:', mediaUrl);
            const video = document.createElement('video');
            video.src = mediaUrl;
            video.controls = true;
            video.autoplay = !isPaused; // Only autoplay if not paused
            video.muted = false;
            
            // Force the video to take the full size of its container
            video.style.width = '100%';
            video.style.height = '100%';
            video.style.maxHeight = '90vh';
            video.style.objectFit = 'contain';
            
            // Create a wrapper div to help control dimensions
            const videoWrapper = document.createElement('div');
            videoWrapper.style.width = '100%';
            videoWrapper.style.height = '100%';
            videoWrapper.style.display = 'flex';
            videoWrapper.appendChild(video);
            
            slide.appendChild(videoWrapper);
            
            // Handle video events as in the original loadCurrentStory function
            video.addEventListener('loadedmetadata', function() {
                // Once we know the video duration, decide how to handle it
                const videoLength = video.duration;
                console.log(`Video duration: ${videoLength}s, Auto-progress delay: ${autoProgressDelay/1000}s`);
                
                // Clear any existing video timer first
                if (video.videoTimer) {
                    clearTimeout(video.videoTimer);
                    video.videoTimer = null;
                }
                
                if (videoLength > autoProgressDelay/1000) {
                    // For longer videos, we'll let them play through once
                    console.log('Video is longer than auto-progress delay, will play once');
                    video.loop = false;
                } else {
                    // For shorter videos, loop until we reach the delay time
                    console.log('Video is shorter than auto-progress delay, will loop');
                    video.loop = true;
                    
                    // Set up a timer to move to next story after delay
                    if (!isPaused) {
                        video.videoTimer = setTimeout(() => {
                            if (!isPaused && !isNavigating) {
                                console.log(`Auto-progress timer completed after ${autoProgressDelay/1000}s`);
                                navigateStory(1);
                            }
                        }, autoProgressDelay);
                    }
                }
                
                // Start progress bar animation
                if (!isPaused) {
                    storyProgress.style.transition = `width ${autoProgressDelay}ms linear`;
                    storyProgress.style.width = '100%';
                }
            });
            
            // Store the video element in a variable accessible to the togglePause function
            currentVideoElement = video;
            
        } else {
            console.log('Loading image story:', mediaUrl);
            const img = document.createElement('img');
            
            // Check if there's a WebP version available for non-WebP images
            if (!mediaUrl.endsWith('.webp') && 
                (mediaUrl.endsWith('.jpg') || mediaUrl.endsWith('.jpeg') || 
                 mediaUrl.endsWith('.png') || mediaUrl.endsWith('.gif'))) {
                
                // Try to use WebP version if it exists
                const webpUrl = mediaUrl.replace(/\.(jpg|jpeg|png|gif)$/i, '.webp');
                
                img.onerror = function() {
                    this.onerror = null; // Prevent infinite loop
                    this.src = mediaUrl; // Fall back to original
                };
                
                img.src = webpUrl;
            } else {
                img.src = mediaUrl;
            }
            
            img.alt = storyData.tt || 'Instagram Story';
            slide.appendChild(img);
            
            // Start auto-progress for images
            if (!isPaused && !isNavigating) {
                startAutoProgressTimer();
            }
        }
        
        // Update navigation buttons visibility - always show both buttons for circular navigation
        storyPrev.style.display = 'flex';
        storyNext.style.display = 'flex';
    }
    
    // Navigate to previous/next story
    function navigateStory(direction) {
        // Prevent rapid clicks from causing issues
        if (isNavigating) return;
        isNavigating = true;
        
        // If we're paused and this is an automatic navigation (not user-initiated),
        // don't advance to the next story
        const isUserInitiated = event && (event.type === 'click' || event.type === 'keydown');
        if (isPaused && direction > 0 && !isUserInitiated) {
            console.log('Auto-navigation blocked because story is paused');
            isNavigating = false;
            return;
        }
        
        // Always clear any existing timers first
        clearAutoProgressTimer();
        
        // Calculate the new index with circular navigation
        let newIndex = currentStoryIndex + direction;
        
        // Implement circular navigation (only once)
        if (newIndex < 0) {
            newIndex = storyItems.length - 1; // Wrap to the last story
            console.log('Wrapping to the last story');
        } else if (newIndex >= storyItems.length) {
            newIndex = 0; // Wrap to the first story
            console.log('Wrapping to the first story');
        }
        
        // Get the current slide for animation
        const currentSlide = storyMedia.querySelector('.media-slide.active');
        
        // Animate the current slide out (instant when reduced motion is on)
        if (currentSlide) {
            const slideDur = reduceMotion ? '0s' : '0.5s';
            currentSlide.style.transition = `transform ${slideDur} ease`;
            currentSlide.style.transform = `translateX(${direction < 0 ? '100%' : '-100%'})`;

            // Create and prepare the new slide with initial position
            const newSlide = document.createElement('div');
            newSlide.className = 'media-slide';
            newSlide.style.transition = 'none'; // No transition initially
            newSlide.style.transform = `translateX(${direction > 0 ? '100%' : '-100%'})`; // Start from right or left
            newSlide.style.opacity = '1';

            // Load the content into the new slide
            loadStoryContent(newSlide, newIndex);
            storyMedia.appendChild(newSlide);

            // Force a reflow to ensure the initial transform is applied
            newSlide.offsetHeight;

            // Now animate the slide into view
            newSlide.style.transition = `transform ${slideDur} ease`;
            newSlide.style.transform = 'translateX(0)';

            // After animation completes, update to the new story
            setTimeout(() => {
                currentStoryIndex = newIndex;
            
                // Remove old slides
                const oldSlides = storyMedia.querySelectorAll('.media-slide:not(:last-child)');
                oldSlides.forEach(slide => slide.remove());
            
                // Make the new slide active
                newSlide.classList.add('active');
            
                // Update URL
                const timestamp = storyItems[currentStoryIndex].getAttribute('data-timestamp');
                if (timestamp) {
                    const url = new URL(window.location.href);
                    url.searchParams.set('story', timestamp);
                    window.history.pushState({}, '', url);
                }
            
                // Reset navigation lock
                isNavigating = false;
            }, reduceMotion ? 0 : 500);
        } else {
            // If no current slide (shouldn't happen), just load the new story
            currentStoryIndex = newIndex;
            loadCurrentStory();
        
            // Update URL
            const timestamp = storyItems[currentStoryIndex].getAttribute('data-timestamp');
            if (timestamp) {
                const url = new URL(window.location.href);
                url.searchParams.set('story', timestamp);
                window.history.pushState({}, '', url);
            }
        
            // Reset navigation lock
            isNavigating = false;
        }
    }
    
    // Close the story viewer
    function closeStory() {
        // Pause any playing videos before closing
        const videoElements = storyMedia.querySelectorAll('video');
        videoElements.forEach(video => {
            if (video && !video.paused) {
                video.pause();
            }
        });
        
        clearAutoProgressTimer();
        storyViewer.style.display = 'none';
        document.body.style.overflow = ''; // Restore scrolling

        // Viewer closed: restore the background and return focus to the trigger
        storyOpen = false;
        setBackgroundInert(false);

        // Remove story parameter from URL
        const url = new URL(window.location.href);
        url.searchParams.delete('story');
        window.history.pushState({}, '', url);

        if (lastFocused && typeof lastFocused.focus === 'function') {
            lastFocused.focus();
        }
    }
    
    // Get pause button element
    const storyPause = document.getElementById('storyPause');
    const pauseIcon = document.getElementById('pauseIcon');
    const playIcon = document.getElementById('playIcon');
    let isPaused = false;
    let currentVideoElement = null; // Track the current video element
    
    // Expose an open-by-index hook so other views (e.g. "On this day") can
    // open the story viewer in place; it locates the real tile by data-index.
    window.mmOpenStory = openStory;

    // Event listeners
    storyClose.addEventListener('click', closeStory);
    storyPrev.addEventListener('click', () => navigateStory(-1));
    storyNext.addEventListener('click', () => navigateStory(1));
    storyPause.addEventListener('click', togglePause);
    
    // Toggle pause function
    function togglePause() {
        console.log('Toggle pause called, current state:', isPaused);
        isPaused = !isPaused;
        
        if (isPaused) {
            console.log('Pausing story playback');
            // Show play icon when paused
            pauseIcon.style.display = 'none';
            playIcon.style.display = 'block';
            storyPause.setAttribute('aria-label', 'Play');
            storyPause.setAttribute('aria-pressed', 'true');

            // Clear the timer and stop progress
            clearAutoProgressTimer();
            storyProgress.style.transition = 'none';
            
            // Don't pause videos, let them continue playing in loop
            console.log('Video will continue playing but auto-advance is disabled');
            
            // Get the current video if there is one
            const videoElement = storyMedia.querySelector('video');
            if (videoElement && videoElement.videoTimer) {
                clearTimeout(videoElement.videoTimer);
                videoElement.videoTimer = null;
            }
        } else {
            console.log('Resuming story playback');
            // Show pause icon when playing
            pauseIcon.style.display = 'block';
            playIcon.style.display = 'none';
            storyPause.setAttribute('aria-label', 'Pause');
            storyPause.setAttribute('aria-pressed', 'false');

            // Get the media element in the story viewer
            const videoElement = storyMedia.querySelector('video');
            const isVideo = videoElement !== null;
            
            console.log('Is video:', isVideo);
            
            if (!isVideo) {
                console.log('Starting auto progress timer for image');
                startAutoProgressTimer();
            } else {
                console.log('Playing video');
                videoElement.play();
            }
        }
    }
    
    // Keyboard navigation
    document.addEventListener('keydown', function(e) {
        if (e.key === 'Tab') {
            trapStoryFocus(e);
            return;
        }
        if (storyViewer.style.display !== 'none') {
            if (e.key === 'ArrowLeft') {
                navigateStory(-1);
            } else if (e.key === 'ArrowRight') {
                navigateStory(1);
            } else if (e.key === 'Escape') {
                closeStory();
            }
        }
    });
    
    // Click on the story media area to navigate forward
    storyMedia.addEventListener('click', function(e) {
        // Only if it's not a video (to avoid interfering with video controls)
        if (!e.target.matches('video')) {
            navigateStory(1);
        }
    });
    
    // Check URL for story parameter on page load
    function checkUrlForStory() {
        const urlParams = new URLSearchParams(window.location.search);
        const storyTimestamp = urlParams.get('story');
        if (!storyTimestamp) return;

        // Resolve the index straight from the data first: on the timeline page
        // the deep-linked story may live in a month that isn't rendered yet
        // (built lazily), so the tile lookup below would miss it. month-nav's
        // DCL handler builds+shows that month synchronously, so by the time
        // this 100ms timer fires openStory's live .story-item query succeeds.
        let storyIndex = -1;
        if (window.storiesData && window.storiesData[storyTimestamp]) {
            storyIndex = window.storiesData[storyTimestamp].i;
        } else {
            const storyItem = Array.from(storyGridItems).find(
                item => item.getAttribute('data-timestamp') === storyTimestamp
            );
            if (storyItem) storyIndex = parseInt(storyItem.getAttribute('data-index'));
        }

        if (storyIndex !== -1 && storyIndex !== undefined) {
            setTimeout(() => openStory(storyIndex), 100);
        }
    }
    
    // Run URL check
    checkUrlForStory();
});
