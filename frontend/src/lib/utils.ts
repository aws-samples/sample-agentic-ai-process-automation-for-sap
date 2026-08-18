// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

// Two sanctioned icon sizes for the chrome. `size={n}` is an SVG attribute, so
// `.compact` never reached it — these are deliberately fixed, not density-scaled.
// An icon that shrank with density would stop matching the text baseline it sits on.
/** Controls: rail rows, dock toggles, list-header buttons. */
export const ICON_CHROME = 16
/** Icons sitting in a line of text: the heartbeat, status adornments. */
export const ICON_INLINE = 14
