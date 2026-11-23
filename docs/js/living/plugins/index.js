/**
 * Default Plugin Manifest for Kilchberg Pixel-Art Diorama v13.0 Living Layer.
 * Registers all 10 modular living-world plugins in deterministic order.
 */

import { createShorelinePlugin } from './shoreline.js';
import { createVesselsPlugin } from './vessels.js';
import { createPedestriansPlugin } from './pedestrians.js';
import { createTrafficPlugin } from './traffic.js';
import { createTrainsPlugin } from './trains.js';
import { createWildlifePlugin } from './wildlife.js';
import { createSeebadPlugin } from './seebad.js';
import { createSportsPlugin } from './sports.js';
import { createLandmarksPlugin } from './landmarks.js';
import { createAtmospherePlugin } from './atmosphere.js';

export function registerDefaultPlugins(engine) {
  if (!engine || typeof engine.register !== 'function') {
    throw new Error('registerDefaultPlugins: valid LivingEngine instance required');
  }
  const plugins = [
    createShorelinePlugin(),
    createVesselsPlugin(),
    createPedestriansPlugin(),
    createTrafficPlugin(),
    createTrainsPlugin(),
    createWildlifePlugin(),
    createSeebadPlugin(),
    createSportsPlugin(),
    createLandmarksPlugin(),
    createAtmospherePlugin(),
  ];
  for (let i = 0; i < plugins.length; i++) {
    engine.register(plugins[i]);
  }
  return engine;
}
