import type { ReactNode } from "react";
import {
  ArrowUpRight,
  CalendarDays,
  Check,
  Flower2,
  MapPin,
} from "lucide-react";
import { KuraiMark } from "./components";
import type { Meta } from "./types";
import "./pages.css";

export function PageLink({
  to,
  onNavigate,
  children,
  className,
  current,
}: {
  to: string;
  onNavigate: (path: string) => void;
  children: ReactNode;
  className?: string;
  current?: boolean;
}) {
  return (
    <a
      href={to}
      className={className}
      aria-current={current ? "page" : undefined}
      onClick={(e) => {
        if (
          e.button === 0 &&
          !e.metaKey &&
          !e.ctrlKey &&
          !e.shiftKey &&
          !e.altKey
        ) {
          e.preventDefault();
          onNavigate(to);
        }
      }}
    >
      {children}
    </a>
  );
}

export function AboutPage({
  meta,
  onNavigate,
}: {
  meta: Meta | null;
  onNavigate: (path: string) => void;
}) {
  return (
    <article className="info-page" aria-labelledby="about-title">
      <div className="info-intro">
        <p className="eyebrow">
          <Flower2 size={15} /> О проекте «Курай»
        </p>
        <h1 id="about-title" tabIndex={-1}>
          Культура рядом.
          <br />
          <em>Впечатления — ваши.</em>
        </h1>
        <p className="info-lead">
          Большая республика, разные города и тысячи поводов выйти из дома. Мы
          собираем афишу, чтобы находить своё было проще.
        </p>
      </div>
      <div className="about-story">
        <figure className="about-landscape">
          <img
            src="/assets/bashkortostan-editorial.webp"
            alt="Иллюстрация по мотивам Башкортостана: горы, река и цветущий курай"
          />
          <figcaption>
            Место, которое хочется открывать заново.
            <small>Авторская иллюстрация, созданная с помощью ИИ.</small>
          </figcaption>
        </figure>
        <div className="about-copy">
          <p className="eyebrow">Ближе к своим. Открытее к новому.</p>
          <h2>
            У каждого города
            <br />
            есть свой голос
          </h2>
          <p>
            Спектакль на родном языке, встреча с любимым музыкантом или семейный
            выходной. «Курай» помогает выбирать события Башкортостана по городу,
            дате, возрасту и бюджету.
          </p>
          <p>
            Название напоминает о курае — одном из символов республики. В
            цветах, орнаменте и линиях гор мы сохраняем связь с местом, которому
            посвящён проект.
          </p>
          {meta && (
            <p className="about-geography">
              <MapPin size={17} />В афише представлены города:{" "}
              {meta.cities.join(", ")}.
            </p>
          )}
          <PageLink to="/" onNavigate={onNavigate} className="button primary">
            Выбрать событие <ArrowUpRight size={18} />
          </PageLink>
        </div>
      </div>
      <section className="about-principles" aria-labelledby="principles-title">
        <div>
          <p className="eyebrow">С вниманием к вашим планам</p>
          <h2 id="principles-title">
            Сначала — источник.
            <br />
            Потом — рекомендация.
          </h2>
        </div>
        <ol>
          <li>
            <span>01</span>
            <div>
              <h3>Можно проверить</h3>
              <p>
                У карточки есть ссылка на афишу учреждения или организатора.
                Неизвестную цену, возраст или длительность отмечаем отдельно.
              </p>
            </div>
          </li>
          <li>
            <span>02</span>
            <div>
              <h3>Можно уточнить</h3>
              <p>
                Помощник разберёт пожелания, а планировщик сопоставит время,
                состав группы и бюджет. Если данных недостаточно, вы увидите,
                что нужно уточнить.
              </p>
            </div>
          </li>
          <li>
            <span>03</span>
            <div>
              <h3>Можно выбрать свой способ</h3>
              <p>
                Пользуйтесь сайтом или Telegram. Сохраняйте интересное и
                подписывайтесь на новые события выбранного города.
              </p>
            </div>
          </li>
        </ol>
      </section>
      <aside className="about-signoff">
        <KuraiMark />
        <div>
          <h2>Афиша растёт вместе с республикой</h2>
          <p>
            Нашли неточность или хотите предложить событие? Напишите нам —
            проверим источник и сведения перед публикацией.
          </p>
        </div>
        <PageLink
          to="/organizers"
          onNavigate={onNavigate}
          className="text-button"
        >
          Предложить событие <ArrowUpRight size={17} />
        </PageLink>
      </aside>
      <p className="info-notice">
        «Курай» — независимый проект. Не является официальным сервисом
        Министерства культуры Республики Башкортостан. Наличие билетов и
        изменения программы уточняйте у организатора.
      </p>
    </article>
  );
}

export function OrganizersPage({
  form,
  onNavigate,
}: {
  form: ReactNode;
  onNavigate: (path: string) => void;
}) {
  return (
    <article className="info-page" aria-labelledby="organizers-title">
      <div className="info-intro">
        <p className="eyebrow">
          <CalendarDays size={15} /> Учреждениям, организаторам и зрителям
        </p>
        <h1 id="organizers-title" tabIndex={-1}>
          Ваше событие.
          <br />
          <em>В общей афише.</em>
        </h1>
        <p className="info-lead">
          Помогите жителям республики узнать о вашей программе. Предложите
          событие или сообщите об изменениях в уже опубликованной карточке.
        </p>
      </div>
      <div className="organizers-layout">
        <section className="organizers-guide" aria-labelledby="proposal-guide">
          <p className="eyebrow">Что понадобится</p>
          <h2 id="proposal-guide">
            Оставьте главное.
            <br />
            Ссылку проверим мы.
          </h2>
          <ul>
            {[
              "Название события и ссылка на его афишу",
              "Дата, время, город, площадка и адрес",
              "Стоимость, возраст и длительность, если известны",
            ].map((line) => (
              <li key={line}>
                <Check size={17} />
                {line}
              </li>
            ))}
          </ul>
          <p>
            Если событие перенесли или отменили, укажите прежнюю карточку и
            ссылку с актуальными сведениями.
          </p>
          <div className="organizers-process">
            <span>Обращение</span>
            <i aria-hidden="true">→</i>
            <span>Проверка</span>
            <i aria-hidden="true">→</i>
            <span>Афиша</span>
          </div>
          <p className="fine-print">
            Сообщение поступает модератору. Отправка обращения не означает
            автоматическую публикацию.
          </p>
        </section>
        <section className="proposal-paper" aria-labelledby="proposal-title">
          <p className="eyebrow">На рассмотрение модератору</p>
          <h2 id="proposal-title">Расскажите о событии</h2>
          {form}
        </section>
      </div>
      <aside className="integration-note">
        <div>
          <p className="eyebrow">Для партнёров</p>
          <h2>Афиша на вашем сайте</h2>
          <p>
            Открытый API и встраиваемый виджет помогут показывать события на
            своей площадке.
          </p>
        </div>
        <a
          href="/api/docs"
          target="_blank"
          rel="noopener noreferrer"
          className="button secondary"
        >
          Документация <ArrowUpRight size={16} />
        </a>
        <PageLink to="/about" onNavigate={onNavigate} className="text-button">
          Узнать о проекте <ArrowUpRight size={16} />
        </PageLink>
      </aside>
    </article>
  );
}
