// Типы данных из контракта API /api/blog (REQUIREMENTS.md).
// Все ответы /api/blog/* возвращаются с cookie-сессией: запросы идут
// с credentials: 'include' (см. api/client.ts).

export interface User {
  id: string;
  username: string;
  email: string;
  image_file: string;
}

// Формат записи реестра articles.yaml, как его отдаёт backend
// (ArticleLang из schema_art.py + вычисляемое complete/file_exists).
// content непустой только в ответе /articles/{art_id} (готовый HTML).
export interface Article {
  author: string;
  lang: string;
  art_id: number;
  title: string;
  file_name: string;
  // Имя раздела (= имя подпапки content_art/); отсутствует или "" для
  // статей в корне content_art/. Приходит в summary /articles
  // (бэкенд: _article_summary) и сохраняется в реестре articles.yaml.
  section?: string;
  content?: string;
  complete?: boolean;
  file_exists?: boolean;
}

// Раздел блога: подпапка content_art/. Отдаётся /api/blog/sections
// (бэкенд: SectionOut). Сортируется на бэкенде по name.
export interface Section {
  name: string;
  label: string;
  count: number;
}