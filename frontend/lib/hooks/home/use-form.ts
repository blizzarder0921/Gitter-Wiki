'use client';

import { useState, useRef } from 'react';
import { initialFormState } from '@/lib/types/home';

/**
 * 首页表单状态管理 Hook
 * 集中管理 GitHub URL 输入、搜索面板状态及搜索相关 ref
 * @returns 表单状态、搜索状态及操作函数
 */
export function useForm() {
  /* 表单状态：GitHub URL 输入 */
  const [form, setForm] = useState(initialFormState);

  /* 搜索面板展开/收起 */
  const [searchOpen, setSearchOpen] = useState(false);

  /* 搜索关键词 */
  const [searchQuery, setSearchQuery] = useState('');

  /* 搜索输入框 DOM 引用 */
  const searchInputRef = useRef<HTMLInputElement>(null);

  /* 搜索按钮 DOM 引用 */
  const searchButtonRef = useRef<HTMLButtonElement>(null);

  return {
    form,
    setForm,
    searchOpen,
    setSearchOpen,
    searchQuery,
    setSearchQuery,
    searchInputRef,
    searchButtonRef,
  };
}
