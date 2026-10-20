'use client';

import React from 'react';
import { motion } from 'framer-motion';

export interface WordByWordTextProps {
  text: string;
  className?: string;
  delay?: number;
}

export function WordByWordText({
  text,
  className = '',
  delay = 0,
}: WordByWordTextProps) {
  // Extract provider tag if attached, e.g. [Powered by Gemini 2.5 Flash]
  const tagMatch = text.match(/(.*?)(\[(?:Powered by|Inferred locally).*?\])\s*$/s);
  const mainText = tagMatch ? tagMatch[1].trim() : text;
  const providerTag = tagMatch ? tagMatch[2].trim().replace(/^\[|\]$/g, '') : null;

  const words = mainText.split(' ').filter(Boolean);

  return (
    <div className={className}>
      <span>
        {words.map((word, idx) => (
          <motion.span
            key={`${word}-${idx}`}
            initial={{ opacity: 0, y: 4, filter: 'blur(3px)' }}
            animate={{ opacity: 1, y: 0, filter: 'blur(0px)' }}
            transition={{
              duration: 0.22,
              delay: delay + idx * 0.035,
              ease: [0.16, 1, 0.3, 1],
            }}
            style={{ display: 'inline-block', marginRight: '0.28em' }}
          >
            {word}
          </motion.span>
        ))}
      </span>

      {providerTag && (
        <motion.div
          initial={{ opacity: 0, y: 3 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{
            duration: 0.3,
            delay: delay + words.length * 0.035 + 0.05,
          }}
          style={{ marginTop: '5px' }}
        >
          <span
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '4px',
              fontSize: '0.66rem',
              fontWeight: 600,
              color: '#4338ca',
              background: '#eef2ff',
              border: '1px solid #c7d2fe',
              padding: '1px 7px',
              borderRadius: '10px',
            }}
          >
            ✨ {providerTag}
          </span>
        </motion.div>
      )}
    </div>
  );
}

export default WordByWordText;
