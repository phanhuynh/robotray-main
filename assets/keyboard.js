(function(){
  if (window.__robotrayKeyboardInstalled) return;
  window.__robotrayKeyboardInstalled = true;

  console.log('[Robotray] Keyboard controls initialized');

  function isTypingTarget(el){
    if (!el) return false;
    const tag = el.tagName ? el.tagName.toLowerCase() : '';
    return tag === 'input' || tag === 'textarea' || tag === 'select' || el.isContentEditable;
  }

  window.addEventListener('keydown', function(ev){
    const keys = ['ArrowUp','ArrowDown','ArrowLeft','ArrowRight','-','='];
    if (!keys.includes(ev.key)) return;
    if (isTypingTarget(ev.target)) return;
    
    ev.preventDefault();
    
    // Map arrow keys to button IDs
    const buttonMap = {
      'ArrowUp': 'btn-y-plus',
      'ArrowDown': 'btn-y-minus',
      'ArrowLeft': 'btn-x-minus',
      'ArrowRight': 'btn-x-plus',
      '-': 'btn-z-minus',
      '=': 'btn-z-plus'
    };
    
    const buttonId = buttonMap[ev.key];
    const button = document.getElementById(buttonId);
    
    console.log(`[Robotray] Arrow key ${ev.key} pressed, button: ${buttonId}, found: ${!!button}, disabled: ${button?.disabled}`);
    
    if (button && !button.disabled) {
      console.log(`[Robotray] Clicking button ${buttonId}`);
      button.click();
    }
  }, {passive:false});
})();
