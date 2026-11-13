export async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(path, options);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(
      body.error?.message || "Не удалось загрузить данные. Попробуйте ещё раз.",
    );
  }
  return response.json();
}
