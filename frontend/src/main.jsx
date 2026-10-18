import React from 'react'
import { createRoot } from 'react-dom/client'
import '@fontsource-variable/inter'
import '@fontsource-variable/jetbrains-mono'
import App from './App.jsx'
import './legacy.css'
import './styles.css'

const root = document.getElementById('root')
createRoot(root).render(<App />)

// Show the app once the text face is ready, so the first paint is already in Inter (no font swap, no reflow).
// index.html carries a timer that reveals the page regardless, so a slow font never leaves it blank.
const reveal = () => root.classList.add('ready')
const fonts = document.fonts
if (fonts?.load) {
  Promise.race([
    Promise.all([fonts.load('400 1em "Inter Variable"'), fonts.load('600 1em "Inter Variable"')]),
    new Promise((resolve) => setTimeout(resolve, 900)),
  ]).then(() => requestAnimationFrame(reveal), reveal)
} else reveal()
