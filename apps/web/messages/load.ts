/**
 * A locale's messages: the pages' own file, plus the widgets' file under `widgets`. The two files
 * have different owners, so neither edit touches the other.
 */
export async function loadMessages(locale: string) {
  const [pages, widgets] = await Promise.all([
    import(`./${locale}.json`).then((m) => m.default),
    import(`./widgets.${locale}.json`).then((m) => m.default),
  ]);
  return { ...pages, widgets };
}
