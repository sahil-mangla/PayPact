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
  const words = text.split(' ');

  return (
    <span className={className}>
      {words.map((word, idx) => (
        <motion.span
          key={`${word}-${idx}`}
          initial={{ opacity: 0, y: 5, filter: 'blur(4px)' }}
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
  );
}

export default WordByWordText;
