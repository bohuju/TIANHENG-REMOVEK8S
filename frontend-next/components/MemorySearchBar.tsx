'use client';

import { useState } from 'react';
import { IconButton, InputAdornment, TextField } from '@mui/material';
import SearchIcon from '@mui/icons-material/Search';

interface MemorySearchBarProps {
  onSearch: (q: string) => void;
}

export function MemorySearchBar({ onSearch }: MemorySearchBarProps) {
  const [value, setValue] = useState('');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onSearch(value.trim());
  };

  return (
    <form onSubmit={handleSubmit}>
      <TextField
        fullWidth
        size="small"
        placeholder="搜索记忆关键词..."
        value={value}
        onChange={(e) => setValue(e.target.value)}
        slotProps={{
          input: {
            endAdornment: (
              <InputAdornment position="end">
                <IconButton size="small" type="submit" aria-label="搜索">
                  <SearchIcon fontSize="small" />
                </IconButton>
              </InputAdornment>
            ),
          },
        }}
      />
    </form>
  );
}
