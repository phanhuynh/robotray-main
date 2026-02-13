// Script to remove scrollbars from Plotly plots
document.addEventListener('DOMContentLoaded', function() {
    const iframes = document.querySelectorAll('.plot-iframe');
    
    iframes.forEach(iframe => {
        iframe.onload = function() {
            try {
                const iframeDoc = iframe.contentDocument || iframe.contentWindow.document;
                
                // Hide scrollbars in iframe
                iframeDoc.documentElement.style.overflow = 'hidden';
                iframeDoc.body.style.overflow = 'hidden';
                
                // Remove scrollbar width
                iframeDoc.documentElement.style.scrollbarWidth = 'none';
                iframeDoc.body.style.scrollbarWidth = 'none';
                
                // Webkit browsers
                const style = iframeDoc.createElement('style');
                style.textContent = `
                    html::-webkit-scrollbar,
                    body::-webkit-scrollbar,
                    *::-webkit-scrollbar {
                        display: none;
                    }
                    html, body {
                        overflow: hidden !important;
                        margin: 0;
                        padding: 0;
                    }
                `;
                iframeDoc.head.appendChild(style);
            } catch(e) {
                console.log('Could not access iframe:', e);
            }
        };
    });
});
